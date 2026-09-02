"""L'atelier de codage — ce qui manque pour que la répartition thématique compte.

L'état des lieux, écrit noir sur blanc dans `cap.py` : α = 0,599, un seul
annotateur, cinquante unités. En dessous de 0,67 la mesure n'est pas publiable,
et ce n'est pas la consigne du modèle qui est en cause — les désaccords restants
sont dispersés, ce qui est la signature d'une ambiguïté d'annotation. Continuer
à régler le prompt contre ces cinquante étiquettes reviendrait à apprendre UN
annotateur, pas la grille.

Ce qui débloque, et que seul un humain peut faire : coder davantage d'unités, et
qu'un second codeur indépendant le fasse aussi. D'où cet écran. Il ne calcule
rien de nouveau — `reliability.py` sait déjà mesurer un alpha — il rend
seulement possible d'y mettre autre chose qu'un fichier annoté à la main une
fois pour toutes.

Les déclarations sont proposées dans un ordre stable et arbitraire (par
identifiant), pas « les plus faciles » ni « celles où le modèle hésite » :
choisir les unités selon la réponse du modèle fabriquerait un échantillon qui
flatte ou qui accable, et l'alpha ne mesurerait plus rien.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database import get_db
from src.models.annotation import CapAnnotation
from src.models.claim import Claim
from src.services.analysis.cap import CAP_VERSION, MAJOR, RELIABILITY, label
from src.services.analysis.reliability import krippendorff_alpha, verdict

router = APIRouter(prefix="/codage", tags=["codage"])

# Une catégorie à part entière, pas un refus de répondre : une part notable du
# corpus est de l'attaque et du positionnement, sans objet d'action publique.
HORS = "hors"


class Decision(BaseModel):
    claim_id: int
    coder: str
    code: int | None = None


@router.get("/grille")
async def grille():
    """Les 21 topiques, avec leur aide au codage. Le vocabulaire du codeur."""
    return {
        "version": CAP_VERSION,
        "topiques": [{"code": c, "label": MAJOR[c][0], "aide": MAJOR[c][1]}
                     for c in sorted(MAJOR)],
    }


@router.get("/suivant")
async def suivant(
    coder: str = Query(..., min_length=1, max_length=40),
    db: AsyncSession = Depends(get_db),
):
    """La prochaine déclaration à coder pour ce codeur.

    Le code de la machine n'est PAS renvoyé : le voir avant de décider ferait
    du codeur un relecteur, et l'accord mesuré ne serait plus indépendant —
    c'est le biais d'ancrage, et il suffit à rendre un alpha inutilisable.
    """
    # Les déclarations déjà codées par la machine d'abord — ce sont elles qui
    # forment une paire, donc une mesure. Mais on ne s'y limite pas : attendre
    # que la machine ait tout codé pour laisser un humain commencer bloquerait
    # le seul travail qui puisse débloquer la mesure.
    deja = select(CapAnnotation.claim_id).where(CapAnnotation.coder == coder)
    c = (await db.execute(
        select(Claim)
        .where(Claim.id.notin_(deja), Claim.verbatim.isnot(None))
        .order_by(Claim.cap_version.is_(None), Claim.id).limit(1)
    )).scalars().first()

    faites = await db.scalar(
        select(func.count()).select_from(CapAnnotation)
        .where(CapAnnotation.coder == coder)) or 0
    if c is None:
        return {"claim": None, "faites": faites}
    return {
        "claim": {"id": c.id, "texte": c.canonical or c.verbatim,
                  "published_at": c.published_at},
        "faites": faites,
    }


@router.post("")
async def coder(d: Decision, db: AsyncSession = Depends(get_db)):
    """Enregistre une décision. Reposter la même unité corrige la précédente."""
    if d.code is not None and int(d.code) not in MAJOR:
        raise HTTPException(400, "code hors grille")
    if await db.get(Claim, d.claim_id) is None:
        raise HTTPException(404, "déclaration introuvable")

    ligne = (await db.execute(
        select(CapAnnotation).where(CapAnnotation.claim_id == d.claim_id,
                                    CapAnnotation.coder == d.coder)
    )).scalars().first()
    if ligne is None:
        ligne = CapAnnotation(claim_id=d.claim_id, coder=d.coder)
        db.add(ligne)
    ligne.code = d.code
    ligne.decided_at = datetime.now(timezone.utc)
    await db.commit()
    return {"ok": True, "code": d.code, "label": label(d.code) if d.code else "hors politique publique"}


@router.get("/fiabilite")
async def fiabilite(db: AsyncSession = Depends(get_db)):
    """L'alpha entre chaque paire de codeurs, machine comprise.

    « hors politique publique » est codé comme une catégorie explicite et non
    comme une donnée manquante : c'est une décision, et l'écarter du calcul
    gonflerait l'accord sur les seules unités faciles.
    """
    rows = (await db.execute(
        select(CapAnnotation.claim_id, CapAnnotation.coder, CapAnnotation.code)
    )).all()
    if not rows:
        return {"mesures": [], "reference": RELIABILITY,
                "note": "aucune annotation humaine pour l'instant"}

    par_codeur: dict[str, dict[int, object]] = {}
    for cid, qui, code in rows:
        par_codeur.setdefault(qui, {})[cid] = HORS if code is None else code

    machine = {
        cid: (HORS if code is None else code)
        for cid, code in (await db.execute(
            select(Claim.id, Claim.cap_major)
            .where(Claim.cap_version.startswith(CAP_VERSION),
                   Claim.id.in_({cid for cid, _, _ in rows}))
        )).all()
    }
    par_codeur["machine"] = machine

    mesures = []
    noms = sorted(par_codeur)
    for i, a in enumerate(noms):
        for b in noms[i + 1:]:
            communs = sorted(set(par_codeur[a]) & set(par_codeur[b]))
            if len(communs) < 10:
                # Sous une dizaine d'unités, un alpha ne dit rien : il varie de
                # 0,2 d'une unité à l'autre. Mieux vaut ne pas l'afficher que
                # d'afficher un nombre qu'on devra désavouer.
                mesures.append({"a": a, "b": b, "n": len(communs), "alpha": None,
                                "verdict": "trop peu d'unités communes"})
                continue
            alpha = krippendorff_alpha(
                [[par_codeur[a][u], par_codeur[b][u]] for u in communs])
            mesures.append({"a": a, "b": b, "n": len(communs),
                            "alpha": None if alpha is None else round(alpha, 3),
                            "verdict": verdict(alpha)})
    return {"mesures": mesures, "reference": RELIABILITY,
            "par_codeur": {q: len(v) for q, v in par_codeur.items()}}
