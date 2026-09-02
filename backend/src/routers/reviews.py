"""Les revues — la lecture hebdomadaire, sujet par sujet.

Chaque paragraphe est rendu avec les déclarations qu'il cite, résolues en
verbatim, locuteur, date et source. C'est la différence entre une synthèse et
une revue d'observatoire : le lecteur peut remonter à ce qui a été dit, phrase
par phrase, sans quitter la page.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database import get_db
from src.models.claim import Claim
from src.models.review import Review
from src.models.subject import Subject
from src.services.analysis.claim_sources import resolve_claim_urls

router = APIRouter(prefix="/reviews", tags=["reviews"])


def _entete(r: Review, sujet: Subject | None) -> dict:
    return {
        "id": r.id, "cadence": r.cadence, "period": r.period,
        "subject_id": r.subject_id,
        "subject_label": (sujet.label if sujet else None),
        # Le statut accompagne le libellé : un sujet resté en « auto » porte les
        # mots-clés de son regroupement, et la page doit pouvoir le signaler
        # plutôt que de les présenter comme un nom.
        "subject_status": (sujet.status if sujet else None),
        "theme": (sujet.theme if sujet else None),
        "title": r.title, "status": r.status,
        "n_paragraphes": len(r.body or []),
        "n_sources": len(r.claim_ids or []),
        "generated_at": r.generated_at,
    }


@router.get("")
async def list_reviews(
    period: str | None = Query(None, description="Semaine ISO, ex. 2026-W36"),
    limit: int = Query(30, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """Le sommaire, de la semaine la plus récente à la plus ancienne."""
    q = select(Review).order_by(Review.period.desc(), Review.id.desc()).limit(limit)
    if period:
        q = q.where(Review.period == period)
    revues = list((await db.execute(q)).scalars().all())

    sujets = {}
    if revues:
        sujets = {s.id: s for s in (await db.execute(
            select(Subject).where(Subject.id.in_({r.subject_id for r in revues}))
        )).scalars().all()}

    # Les semaines disponibles, pour naviguer sans deviner les clés.
    periodes = [p for (p,) in (await db.execute(
        select(Review.period).group_by(Review.period).order_by(Review.period.desc())
    )).all()]
    total = await db.scalar(select(func.count()).select_from(Review)) or 0
    return {"total": total, "periods": periodes,
            "items": [_entete(r, sujets.get(r.subject_id)) for r in revues]}


@router.get("/{review_id}")
async def get_review(review_id: int, db: AsyncSession = Depends(get_db)):
    """Une revue, ses paragraphes, et sous chacun ce qu'il cite."""
    r = await db.get(Review, review_id)
    if r is None:
        raise HTTPException(404, "revue introuvable")
    sujet = await db.get(Subject, r.subject_id)

    claims = list((await db.execute(
        select(Claim).where(Claim.id.in_(r.claim_ids or []))
    )).scalars().all())
    urls = await resolve_claim_urls(db, claims)
    par_id = {
        c.id: {
            "id": c.id, "speaker": c.speaker_name, "party": c.party,
            "published_at": c.published_at, "platform": c.platform,
            "text": c.canonical or c.verbatim, "url": urls.get(c.id),
        }
        for c in claims
    }

    return {
        **_entete(r, sujet),
        "paragraphes": [
            {"texte": p.get("texte", ""),
             # Une source citée mais disparue depuis (déclaration supprimée du
             # corpus) ne casse pas la page : elle manque, et ça se voit.
             "sources": [par_id[i] for i in p.get("claim_ids", []) if i in par_id]}
            for p in (r.body or [])
        ],
    }
