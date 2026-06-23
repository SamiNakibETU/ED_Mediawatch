from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database import get_db
from src.models.article import Article
from src.models.media_source import MediaSource
from src.schemas import ArticlePage, CollectionStats
from src.security import require_token
from src.services.archive.archiver import run_archival
from src.services.collection.press_collector import run_press_collection

router = APIRouter(tags=["press"])


@router.get("/articles", response_model=ArticlePage)
async def articles(
    leaning: str | None = Query(None, description="far_right/right/center/left/far_left"),
    source: str | None = Query(None, description="media_source_id"),
    statements_only: bool = Query(False),
    theme: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
) -> ArticlePage:
    stmt = select(Article).order_by(
        Article.published_at.desc().nullslast(), Article.id.desc()
    )
    count_stmt = select(func.count(Article.id))

    if leaning:
        ids = select(MediaSource.id).where(MediaSource.leaning == leaning)
        stmt = stmt.where(Article.media_source_id.in_(ids))
        count_stmt = count_stmt.where(Article.media_source_id.in_(ids))
    if source:
        stmt = stmt.where(Article.media_source_id == source)
        count_stmt = count_stmt.where(Article.media_source_id == source)
    if statements_only:
        stmt = stmt.where(Article.is_statement.is_(True))
        count_stmt = count_stmt.where(Article.is_statement.is_(True))
    if theme:
        stmt = stmt.where(Article.theme == theme)
        count_stmt = count_stmt.where(Article.theme == theme)

    total = await db.scalar(count_stmt) or 0
    res = await db.execute(stmt.limit(limit).offset(offset))
    items = list(res.scalars().all())

    # Enrichir avec le nom + l'orientation de la source (métadonnées de veille).
    srcs = {
        s.id: s
        for s in (await db.execute(select(MediaSource))).scalars().all()
    }
    for art in items:
        src = srcs.get(art.media_source_id)
        if src:
            art.source_name = src.name
            art.leaning = src.leaning

    return ArticlePage(total=total, limit=limit, offset=offset, items=items)


@router.post("/collect-press", response_model=dict, dependencies=[Depends(require_token)])
async def trigger_press() -> dict:
    """Run one French-press collection sweep now."""
    stats = await run_press_collection()
    stats["errors"] = len(stats["errors"])
    return stats


@router.post("/archive-press", response_model=dict, dependencies=[Depends(require_token)])
async def trigger_archive(limit: int = Query(50, ge=1, le=500)) -> dict:
    """Archive not-yet-archived press articles (snapshot local + Wayback)."""
    return await run_archival(kind="press", limit=limit)
