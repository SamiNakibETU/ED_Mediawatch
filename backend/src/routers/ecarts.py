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

REELS = ("revirement", "divergence", "ecart_au_programme")
TYPES = {"temps": "Une même figure dans le temps", "programme": "Contre le programme du parti",
         "parti": "Deux voix du même parti"}


async def _cote(db, decl_id: int | None, figure_id: int | None, parti: str | None, position: str | None,
                enjeu) -> dict | None:
    if not decl_id:
        return None
    d = await db.get(Declaration, decl_id)
    if d is None:
        return None
    post = await db.get(Post, d.post_id)
    pers = await db.get(Personality, figure_id) if figure_id else None
    cran = enjeu.cran(position)
    return {
        "figure": pers.full_name if pers else None, "figure_id": figure_id, "parti": parti,
        "date": d.published_at, "position": position, "label": cran.label if cran else position,
        "verbatim": d.verbatim, "modalite": d.modalite,
        "source": {"kind": "tweet", "url": post.url, "text": post.content, "published_at": post.published_at,
                   "archive": post.snapshot_url, "author": pers.handle if pers else None,
                   "post_type": post.post_type, "quoted_author": post.quoted_handle,
                   "quoted_text": post.quoted_content, "truncated": bool(post.text_truncated)},
    }


@router.get("")
async def list_ecarts(
    type: str | None = None, statut: str = Query("a_relire"), enjeu: str | None = None,
    force_min: int = 0, juge: str = Query("tous"), limit: int = Query(30, le=100), offset: int = 0,
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
    if juge == "reels":
        stmt = stmt.where((Ecart.juge_type.is_(None)) | (
            Ecart.juge_type.in_(REELS) & (Ecart.juge_force >= 2)))
    elif juge == "lectures":
        stmt = stmt.where(Ecart.juge_type.in_(("erreur_de_lecture", "contexte_different", "nuance")))
    total = await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = (await db.execute(
        stmt.order_by(Ecart.juge_force.desc().nullslast(), Ecart.ampleur.desc(), Ecart.date_b.desc().nullslast())
        .limit(limit).offset(offset))).scalars().all()
    items = []
    for e in rows:
        enj = PAR_SLUG.get(e.enjeu)
        if enj is None:
            continue
        a = await _cote(db, e.decl_a_id, e.figure_a_id, e.parti_a, e.position_a, enj)
        b = await _cote(db, e.decl_b_id, e.figure_b_id, e.parti_b, e.position_b, enj)
        prog = None
        if e.engagement_id:
            g = await db.get(EngagementProgramme, e.engagement_id)
            if g:
                prog = {"parti": g.parti, "annee": g.annee, "livret": g.livret, "page": g.page,
                        "label": enj.cran(g.position).label if enj.cran(g.position) else g.position,
                        "verbatim": g.verbatim}
        items.append({
            "id": e.id, "type": e.type, "type_label": TYPES.get(e.type, e.type), "enjeu": e.enjeu,
            "titre": enj.titre, "question": enj.question, "ampleur": e.ampleur, "statut": e.statut,
            "a": a, "b": b, "programme": prog,
            "juge": {"type": e.juge_type, "force": e.juge_force, "justification": e.juge_justification,
                     "explication": e.juge_explication} if e.juge_type else None,
            "decision_note": e.decision_note,
        })
    return {"total": total, "items": items}


@router.get("/compte")
async def compte(db: AsyncSession = Depends(get_db)) -> dict:
    rows = (await db.execute(select(Ecart.type, Ecart.statut, func.count()).group_by(Ecart.type, Ecart.statut))).all()
    out: dict = {t: {s: 0 for s in STATUTS} for t in TYPES}
    for t, s, n in rows:
        out.setdefault(t, {s2: 0 for s2 in STATUTS})[s] = n
    return {"types": TYPES, "compte": out}


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
