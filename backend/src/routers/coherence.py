"""L'indice de cohérence par parti et par enjeu (définition dans services/analysis/coherence.py)."""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from src.database import get_db
from src.services.analysis.coherence import indice

router = APIRouter(prefix="/coherence", tags=["coherence"])


@router.get("")
async def get_coherence(db: AsyncSession = Depends(get_db)) -> dict:
    return await indice(db)
