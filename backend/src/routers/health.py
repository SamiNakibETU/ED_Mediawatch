from fastapi import APIRouter
from sqlalchemy import func, select

from src.database import get_session_factory
from src.models.personality import Personality
from src.models.post import Post

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict:
    factory = get_session_factory()
    async with factory() as db:
        n_personalities = await db.scalar(select(func.count(Personality.id)))
        n_active = await db.scalar(
            select(func.count(Personality.id)).where(
                Personality.is_active.is_(True), Personality.handle.isnot(None)
            )
        )
        n_posts = await db.scalar(select(func.count(Post.id)))
    return {
        "status": "ok",
        "personalities": n_personalities or 0,
        "active_with_handle": n_active or 0,
        "posts": n_posts or 0,
    }
