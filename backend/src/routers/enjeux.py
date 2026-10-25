"""Le registre des positions, en lecture : la liste des enjeux et leurs fiches."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from src.database import get_db
from src.services.analysis.positions import fiche, hors_liste, sommaire

router = APIRouter(prefix="/enjeux", tags=["enjeux"])


@router.get("")
async def list_enjeux(db: AsyncSession = Depends(get_db)) -> list[dict]:
    return await sommaire(db)


@router.get("/hors-liste")
async def get_hors_liste(db: AsyncSession = Depends(get_db)) -> list[dict]:
    """Les objets de déclaration qu'aucune question du référentiel ne couvre."""
    return await hors_liste(db)


@router.get("/{slug}")
async def get_enjeu(slug: str, db: AsyncSession = Depends(get_db)) -> dict:
    out = await fiche(db, slug)
    if out is None:
        raise HTTPException(404, "enjeu inconnu")
    return out
