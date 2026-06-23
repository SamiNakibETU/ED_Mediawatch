"""Le Compteur — « à combien le chiffrez-vous ? »

Pour chaque référent suivi, toutes les valeurs annoncées dans le temps, par qui.
Matérialise « les chiffres ne collent pas » : dispersion d'un coup d'œil.
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database import get_db
from src.models.claim import Claim
from src.security import require_token
from src.models.referentiel import Referent

router = APIRouter(tags=["compteur"])


@router.get("/compteurs")
async def list_compteurs(db: AsyncSession = Depends(get_db)) -> dict:
    """Référents quantitatifs ayant des claims, avec dispersion des valeurs."""
    rows = (
        await db.execute(
            select(
                Claim.referent_key,
                func.count(Claim.id),
                func.min(Claim.qty_value),
                func.max(Claim.qty_value),
                func.avg(Claim.qty_value),
                Claim.qty_unit,
            )
            .where(Claim.qty_value.isnot(None), Claim.referent_key.isnot(None))
            .group_by(Claim.referent_key, Claim.qty_unit)
            .order_by(func.count(Claim.id).desc())
        )
    ).all()

    labels = dict(
        (await db.execute(select(Referent.key, Referent.label))).all()
    )
    out = []
    for key, n, vmin, vmax, vavg, unit in rows:
        spread = (vmax - vmin) if (vmax is not None and vmin is not None) else 0
        out.append({
            "referent_key": key,
            "label": labels.get(key, key),
            "unit": unit,
            "n_claims": n,
            "min": vmin, "max": vmax, "avg": round(vavg, 2) if vavg else None,
            "spread": round(spread, 2),
        })
    return {"compteurs": out}


@router.get("/compteur")
async def compteur(
    key: str = Query(..., description="referent_key"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Série temporelle de toutes les valeurs annoncées pour un référent."""
    ref = await db.get(Referent, key)
    claims = (
        await db.execute(
            select(Claim)
            .where(Claim.referent_key == key, Claim.qty_value.isnot(None))
            .order_by(Claim.published_at.asc().nullslast())
        )
    ).scalars().all()

    points = [
        {
            "claim_id": c.id,
            "value": c.qty_value,
            "unit": c.qty_unit,
            "speaker": c.speaker_name,
            "party": c.party,
            "platform": c.platform,
            "published_at": c.published_at,
            "verbatim": c.verbatim,
            "confidence": c.confidence,
            "human_validated": c.human_validated,
        }
        for c in claims
    ]
    return {
        "referent_key": key,
        "label": ref.label if ref else key,
        "unit": ref.unit if ref else None,
        "n": len(points),
        "points": points,
    }


@router.post("/extract-claims", dependencies=[Depends(require_token)])
async def trigger_extract(
    use_llm: bool | None = Query(None),
    reset: bool = Query(False, description="purge les claims existants avant de rejouer"),
) -> dict:
    """Extraction des claims quantitatifs (posts + presse).

    use_llm: None = suit LLM_REFINE_ENABLED ; true/false = force le raffinage LLM.
    reset: vide la table claims d'abord (les contradictions liées sont
    supprimées en cascade) — utile pour rejouer après un changement de logique LLM.
    """
    from src.services.analysis.claim_extractor import run_claim_extraction

    return await run_claim_extraction(use_llm=use_llm, reset=reset)
