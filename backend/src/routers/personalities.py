from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database import get_db
from src.models.personality import Personality
from src.schemas import PersonalityOut

router = APIRouter(prefix="/personalities", tags=["personalities"])


@router.get("", response_model=list[PersonalityOut])
async def list_personalities(
    group: str | None = Query(None, description="Filter by group_code (RN/UDR/FIGURE)"),
    with_handle: bool = Query(False),
    db: AsyncSession = Depends(get_db),
) -> list[Personality]:
    stmt = select(Personality).order_by(Personality.group_code, Personality.full_name)
    if group:
        stmt = stmt.where(Personality.group_code == group.upper())
    if with_handle:
        stmt = stmt.where(Personality.handle.isnot(None))
    res = await db.execute(stmt)
    return list(res.scalars().all())
