"""La couverture de la collecte depuis 2022, figure par figure."""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from src.database import get_db
from src.services.collection.couverture import couverture

router = APIRouter(prefix="/couverture", tags=["couverture"])


@router.get("")
async def get_couverture(db: AsyncSession = Depends(get_db)) -> dict:
    return await couverture(db)
