from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.database import get_db
from src.models.referentiel import Subtheme, Theme
from src.security import require_token
from src.services.analysis.embeddings import (
    embed_referents,
    fusion_candidates,
    nearest_referent,
)

router = APIRouter(tags=["referentiel"])


@router.get("/referentiel")
async def get_referentiel(db: AsyncSession = Depends(get_db)) -> dict:
    res = await db.execute(
        select(Theme)
        .options(selectinload(Theme.subthemes).selectinload(Subtheme.referents))
        .order_by(Theme.order)
    )
    themes = res.scalars().unique().all()
    out = []
    for t in themes:
        subs = []
        for st in t.subthemes:
            subs.append({
                "id": st.id, "label": st.label,
                "referents": [
                    {"key": r.key, "label": r.label, "unit": r.unit}
                    for r in st.referents
                ],
            })
        out.append({"id": t.id, "label": t.label, "order": t.order, "subthemes": subs})
    version = themes[0].version if themes else None
    return {"version": version, "themes": out}


@router.post("/embed-referents", dependencies=[Depends(require_token)])
async def post_embed_referents() -> dict:
    """Calcule/cache les embeddings Cohere des référents (idempotent)."""
    return await embed_referents()


@router.get("/referent-neighbors")
async def referent_neighbors(
    sentence: str = Query(..., description="phrase à rattacher au référent le plus proche"),
    top: int = Query(3, ge=1, le=10),
) -> dict:
    return {"sentence": sentence, "matches": await nearest_referent(sentence, top=top)}


@router.get("/referent-fusion")
async def referent_fusion(threshold: float = Query(0.86, ge=0.5, le=1.0)) -> dict:
    """Référents sémantiquement redondants (candidats à fusion/curation)."""
    return {"threshold": threshold, "candidates": await fusion_candidates(threshold)}
