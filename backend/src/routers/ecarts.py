"""Les écarts : la file de relecture, les écarts confirmés, les divergences entre partis."""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database import get_db
from src.models.declaration import Declaration
from src.models.ecart import STATUTS, Ecart
from src.models.engagement_programme import EngagementProgramme
from src.models.personality import Personality
from src.models.post import Post
from src.security import require_token
from src.services.analysis.ecarts import divergences
from src.services.analysis.enjeux import PAR_SLUG

router = APIRouter(prefix="/ecarts", tags=["ecarts"])

TYPES = {"temps": "Une même figure dans le temps", "programme": "Contre le programme du parti",
         "parti": "Deux voix du même parti", "chiffre": "Une même mesure, deux chiffres"}
AUTO = {"retenu": "retenu automatiquement", "faible": "mouvement faible", "ecarte": "écarté automatiquement"}


async def _cote(db, decl_id: int | None, figure_id: int | None, parti: str | None, position: str | None,
                enjeu) -> dict | None:
    if not decl_id:
        return None
    d = await db.get(Declaration, decl_id)
    if d is None:
        return None
    post = await db.get(Post, d.post_id)
    pers = await db.get(Personality, figure_id) if figure_id else None
    cran = enjeu.cran(position) if enjeu else None
    return {
        "figure": pers.full_name if pers else None, "figure_id": figure_id, "parti": parti,
        "date": d.published_at, "position": position, "label": cran.label if cran else position,
        "verbatim": d.verbatim, "modalite": d.modalite,
        "valeur": f"{d.valeur:g} {d.unite}" if d.valeur is not None else None,
        "objet": d.objet, "douteuse": bool(d.douteuse), "doute_motif": d.doute_motif,
        "source": {"kind": "tweet", "url": post.url, "text": post.content, "published_at": post.published_at,
                   "archive": post.snapshot_url, "author": pers.handle if pers else None,
                   "post_type": post.post_type, "quoted_author": post.quoted_handle,
                   "quoted_text": post.quoted_content, "truncated": bool(post.text_truncated)},
    }


@router.get("")
async def list_ecarts(
    type: str | None = None, statut: str = Query("a_relire"), enjeu: str | None = None,
    force_min: int = 0, juge: str = Query("retenu"), limit: int = Query(30, le=100), offset: int = 0,
    db: AsyncSession = Depends(get_db),
) -> dict:
    stmt = select(Ecart).where(Ecart.statut == statut)
    if type:
        stmt = stmt.where(Ecart.type == type)
    if enjeu:
        stmt = stmt.where(Ecart.enjeu == enjeu)
    if force_min:
        stmt = stmt.where(Ecart.juge_force >= force_min)
    # « reels » : ce que le juge tient pour un écart réel, ou qu'il n'a pas
    # encore lu. « lectures » : ce qu'il a relevé comme erreur de lecture ou
    # contexte différent, c'est-à-dire des déclarations à corriger.
    if juge in AUTO:
        stmt = stmt.where(Ecart.auto == juge)
    elif juge == "attente":
        stmt = stmt.where(Ecart.auto.is_(None))
    total = await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = (await db.execute(
        stmt.order_by(Ecart.juge_force.desc().nullslast(), Ecart.ampleur.desc(), Ecart.date_b.desc().nullslast())
        .limit(limit).offset(offset))).scalars().all()
    items = [await _item(db, e) for e in rows]
    return {"total": total, "items": items}


async def _item(db, e: Ecart) -> dict:
    enj = PAR_SLUG.get(e.enjeu)
    a = await _cote(db, e.decl_a_id, e.figure_a_id, e.parti_a, e.position_a, enj)
    b = await _cote(db, e.decl_b_id, e.figure_b_id, e.parti_b, e.position_b, enj)
    prog = None
    if e.engagement_id:
        g = await db.get(EngagementProgramme, e.engagement_id)
        if g:
            prog = {"parti": g.parti, "annee": g.annee, "livret": g.livret, "page": g.page,
                    "label": enj.cran(g.position).label if enj and enj.cran(g.position) else g.position,
                    "verbatim": g.verbatim}
    return {
        "id": e.id, "type": e.type, "type_label": TYPES.get(e.type, e.type), "enjeu": e.enjeu,
        "titre": enj.titre if enj else ((a or {}).get("objet") or "Même mesure, deux chiffres"),
        "question": enj.question if enj else "Même mesure annoncée avec des chiffres différents",
        "ampleur": e.ampleur, "statut": e.statut, "auto": e.auto, "auto_label": AUTO.get(e.auto),
        "a": a, "b": b, "programme": prog,
        "juge": {"type": e.juge_type, "force": e.juge_force, "justification": e.juge_justification,
                 "explication": e.juge_explication} if e.juge_type else None,
        "juge2": {"type": e.juge2_type, "force": e.juge2_force,
                  "explication": e.juge2_explication} if e.juge2_type else None,
        "decision_note": e.decision_note,
    }


def cle_fait(e: Ecart) -> tuple:
    """Le fait derrière une paire. Un même vote ou un même revirement produit beaucoup de paires
    de déclarations : dans un parti, toutes les voix d'un camp contre toutes celles de l'autre ;
    chez une figure, chaque propos d'avant contre chaque propos d'après."""
    if e.type == "parti":
        return (e.type, e.enjeu, e.parti_a, frozenset((e.position_a, e.position_b)))
    if e.type in ("temps", "programme"):
        return (e.type, e.enjeu, e.figure_a_id)
    return (e.type, e.id)


def _rang(e: Ecart) -> tuple:
    return (e.juge_force or 0, e.ampleur or 0, str(e.date_b or e.date_a or ""))


def _filtre(type: str | None, enjeu: str | None, juge: str, figure: int | None = None):
    stmt = select(Ecart).where(Ecart.statut != "ecarte")
    if type:
        stmt = stmt.where(Ecart.type == type)
    if enjeu:
        stmt = stmt.where(Ecart.enjeu == enjeu)
    if figure:
        stmt = stmt.where((Ecart.figure_a_id == figure) | (Ecart.figure_b_id == figure))
    if juge in AUTO:
        stmt = stmt.where(Ecart.auto == juge)
    elif juge == "attente":
        stmt = stmt.where(Ecart.auto.is_(None))
    return stmt


async def faits_de(db, *, type: str | None = None, enjeu: str | None = None, juge: str = "retenu",
                   figure: int | None = None, limit: int = 20, offset: int = 0) -> dict:
    rows = (await db.execute(_filtre(type, enjeu, juge, figure))).scalars().all()
    if juge in ("retenu", "faible"):
        # Une déclaration que d'autres juges ont tenue pour mal lue ne porte plus d'écart : la paire
        # a pu être jugée avant que le doute ne tombe.
        douteuses = set((await db.execute(select(Declaration.id).where(Declaration.douteuse.is_(True)))).scalars())
        rows = [e for e in rows if e.decl_a_id not in douteuses and e.decl_b_id not in douteuses]
    groupes: dict[tuple, list[Ecart]] = {}
    for e in rows:
        groupes.setdefault(cle_fait(e), []).append(e)
    ordre = sorted(groupes.values(), key=lambda g: (max(_rang(e) for e in g), len(g)), reverse=True)
    noms: dict[int, str] = {}
    items = []
    for g in ordre[offset:offset + limit]:
        tete = max(g, key=_rang)
        it = await _item(db, tete)
        it["paires"] = len(g)
        it["periode"] = [min(str(x) for e in g for x in (e.date_a, e.date_b) if x),
                         max(str(x) for e in g for x in (e.date_a, e.date_b) if x)] if any(
                             e.date_a or e.date_b for e in g) else None
        voix = None
        if tete.type == "parti" and len(g) > 1:
            enj = PAR_SLUG.get(tete.enjeu)
            camps: dict[str, dict[int, str]] = {}
            for e in g:
                for fid, pos, d in ((e.figure_a_id, e.position_a, e.date_a), (e.figure_b_id, e.position_b, e.date_b)):
                    if fid and pos:
                        vu = camps.setdefault(pos, {})
                        vu[fid] = max(vu.get(fid, ""), str(d or ""))
            voix = []
            for pos, vu in camps.items():
                for fid in vu:
                    if fid not in noms:
                        pers = await db.get(Personality, fid)
                        noms[fid] = pers.full_name if pers else "?"
                cran = enj.cran(pos) if enj else None
                voix.append({"position": pos, "label": cran.label if cran else pos,
                             "figures": [{"id": fid, "nom": noms[fid], "date": d or None}
                                         for fid, d in sorted(vu.items(), key=lambda kv: kv[1], reverse=True)]})
        it["voix"] = voix
        items.append(it)
    return {"total": len(ordre), "paires": len(rows), "items": items}


@router.get("/faits")
async def list_faits(
    type: str | None = None, enjeu: str | None = None, juge: str = Query("retenu"), figure: int | None = None,
    limit: int = Query(20, le=100), offset: int = 0, db: AsyncSession = Depends(get_db),
) -> dict:
    """Les écarts regroupés par fait : une carte par mouvement, pas une par paire de déclarations."""
    return await faits_de(db, type=type, enjeu=enjeu, juge=juge, figure=figure, limit=limit, offset=offset)


@router.get("/compte")
async def compte(db: AsyncSession = Depends(get_db)) -> dict:
    rows = (await db.execute(select(Ecart.type, Ecart.auto, func.count()).group_by(Ecart.type, Ecart.auto))).all()
    out: dict = {t: {k: 0 for k in (*AUTO, "attente")} for t in TYPES}
    for t, a, n in rows:
        out.setdefault(t, {k: 0 for k in (*AUTO, "attente")})[a or "attente"] = n
    return {"types": TYPES, "decisions": AUTO, "compte": out}


@router.get("/divergences")
async def get_divergences(jours: int = Query(365, le=5000), db: AsyncSession = Depends(get_db)) -> list[dict]:
    return await divergences(db, depuis_jours=jours)


class Decision(BaseModel):
    statut: str
    note: str | None = None


@router.post("/{ecart_id}/decision", dependencies=[Depends(require_token)])
async def decider(ecart_id: int, d: Decision, db: AsyncSession = Depends(get_db)) -> dict:
    if d.statut not in STATUTS:
        raise HTTPException(400, "statut inconnu")
    e = await db.get(Ecart, ecart_id)
    if e is None:
        raise HTTPException(404, "écart inconnu")
    e.statut, e.decision_note, e.decided_at = d.statut, (d.note or None), datetime.now(timezone.utc)
    await db.commit()
    return {"id": e.id, "statut": e.statut}
