"""Le registre des positions, en lecture : la liste des enjeux et leurs fiches."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from src.database import get_db
from src.services.analysis.positions import etat, fiche, hors_liste, recentes, sommaire

router = APIRouter(prefix="/enjeux", tags=["enjeux"])


@router.get("")
async def list_enjeux(db: AsyncSession = Depends(get_db)) -> list[dict]:
    return await sommaire(db)


@router.get("/hors-liste")
async def get_hors_liste(db: AsyncSession = Depends(get_db)) -> list[dict]:
    """Les objets de déclaration qu'aucune question du référentiel ne couvre."""
    return await hors_liste(db)


@router.get("/recentes")
async def get_recentes(limit: int = 10, db: AsyncSession = Depends(get_db)) -> list[dict]:
    """Les dernières déclarations du registre."""
    return await recentes(db, limit=min(limit, 50))


@router.get("/etat")
async def get_etat(db: AsyncSession = Depends(get_db)) -> dict:
    """Le contenu du registre en chiffres, avec le nombre d'écarts retenus par les juges."""
    from src.routers.ecarts import faits_de

    out = await etat(db)
    for juge in ("retenu", "faible"):
        f = await faits_de(db, juge=juge, limit=1)
        out[f"faits_{juge}"], out[f"paires_{juge}"] = f["total"], f["paires"]
    return out


@router.get("/{slug}")
async def get_enjeu(slug: str, db: AsyncSession = Depends(get_db)) -> dict:
    out = await fiche(db, slug)
    if out is None:
        raise HTTPException(404, "enjeu inconnu")
    return out
