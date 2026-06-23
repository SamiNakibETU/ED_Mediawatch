from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.database import get_db
from src.models.personality import Personality
from src.models.post import Post
from src.schemas import CollectionStats, FeedPage
from src.security import require_token
from src.services.collection.x_collector import run_collection

router = APIRouter(tags=["feed"])


@router.get("/feed", response_model=FeedPage)
async def feed(
    group: str | None = Query(None, description="RN / UDR / FIGURE"),
    personality_id: int | None = Query(None),
    theme: str | None = Query(None),
    q: str | None = Query(None, description="recherche : nom ou @handle de la personnalité"),
    include_retweets: bool = Query(True),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
) -> FeedPage:
    stmt = (
        select(Post)
        .join(Personality, Post.personality_id == Personality.id)
        .options(selectinload(Post.personality))
        .order_by(Post.published_at.desc().nullslast(), Post.id.desc())
    )
    count_stmt = select(func.count(Post.id)).join(
        Personality, Post.personality_id == Personality.id
    )

    if group:
        stmt = stmt.where(Personality.group_code == group.upper())
        count_stmt = count_stmt.where(Personality.group_code == group.upper())
    if personality_id:
        stmt = stmt.where(Post.personality_id == personality_id)
        count_stmt = count_stmt.where(Post.personality_id == personality_id)
    if theme:
        stmt = stmt.where(Post.theme == theme)
        count_stmt = count_stmt.where(Post.theme == theme)
    if q and q.strip():
        # Recherche serveur sur toute la base (pas seulement la page chargée).
        like = f"%{q.strip().lstrip('@')}%"
        cond = or_(Personality.full_name.ilike(like), Personality.handle.ilike(like))
        stmt = stmt.where(cond)
        count_stmt = count_stmt.where(cond)
    if not include_retweets:
        stmt = stmt.where(Post.is_retweet.is_(False))
        count_stmt = count_stmt.where(Post.is_retweet.is_(False))

    total = await db.scalar(count_stmt) or 0
    res = await db.execute(stmt.limit(limit).offset(offset))
    items = list(res.scalars().all())
    return FeedPage(total=total, limit=limit, offset=offset, items=items)


@router.post("/collect", response_model=CollectionStats, dependencies=[Depends(require_token)])
async def trigger_collection() -> CollectionStats:
    """Run one collection sweep now (manual trigger, useful in dev)."""
    stats = await run_collection()
    return CollectionStats(**stats)
