"""La revue de la semaine sur X : sujets à la une, tendances, déclarations, écarts."""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from src.database import get_db
from src.services.analysis.revue import revue

router = APIRouter(prefix="/revue", tags=["revue"])


@router.get("")
async def get_revue(semaine: str | None = None, db: AsyncSession = Depends(get_db)) -> dict:
    """Une semaine (« 2026-W43 »), la dernière calculée par défaut."""
    return await revue(db, semaine)
