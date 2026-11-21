"""Les votes à l'Assemblée des figures suivies (définitions dans services/analysis/votes.py)."""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from src.database import get_db
from src.services.analysis import votes as v

router = APIRouter(prefix="/votes", tags=["votes"])


@router.get("/dissidences")
async def get_dissidences(limit: int = 40, db: AsyncSession = Depends(get_db)) -> dict:
    return await v.dissidences(db, limit=min(limit, 200))


@router.get("/enjeu/{slug}")
async def get_votes_enjeu(slug: str, db: AsyncSession = Depends(get_db)) -> list[dict]:
    return await v.par_enjeu(db, slug)


@router.get("/figure/{figure_id}")
async def get_votes_figure(figure_id: int, db: AsyncSession = Depends(get_db)) -> dict:
    return await v.de_la_figure(db, figure_id)
