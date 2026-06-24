from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database import get_db
from src.models.article import Article
from src.models.media_source import MediaSource
from src.schemas import ArticleDetail, ArticlePage, CollectionStats
from src.security import require_token
from src.services.archive.archiver import run_archival
from src.services.collection.press_collector import run_press_collection

router = APIRouter(tags=["press"])


def _attach_source(article: Article, src: MediaSource | None) -> Article:
    if src:
        article.source_name = src.name
        article.leaning = src.leaning
    return article


@router.get("/articles", response_model=ArticlePage)
async def articles(
    leaning: str | None = Query(None, description="far_right/right/center/left/far_left"),
    source: str | None = Query(None, description="media_source_id"),
    nature: str | None = Query(None, description="prise_de_parole | mention"),
    statements_only: bool = Query(False),
    theme: str | None = Query(None),
    subtheme: str | None = Query(None),
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
    if nature:
        stmt = stmt.where(Article.nature == nature)
        count_stmt = count_stmt.where(Article.nature == nature)
    if statements_only:
        stmt = stmt.where(Article.is_statement.is_(True))
        count_stmt = count_stmt.where(Article.is_statement.is_(True))
    if theme:
        stmt = stmt.where(Article.theme == theme)
        count_stmt = count_stmt.where(Article.theme == theme)
    if subtheme:
        stmt = stmt.where(Article.subtheme == subtheme)
        count_stmt = count_stmt.where(Article.subtheme == subtheme)

    total = await db.scalar(count_stmt) or 0
    res = await db.execute(stmt.limit(limit).offset(offset))
    items = list(res.scalars().all())

    # Enrichir avec le nom + l'orientation de la source (métadonnées de veille).
    srcs = {
        s.id: s
        for s in (await db.execute(select(MediaSource))).scalars().all()
    }
    for art in items:
        _attach_source(art, srcs.get(art.media_source_id))

    return ArticlePage(total=total, limit=limit, offset=offset, items=items)


@router.get("/articles/{article_id}", response_model=ArticleDetail)
async def article_detail(
    article_id: int, db: AsyncSession = Depends(get_db)
) -> ArticleDetail:
    """Article complet (texte intégral) pour le panneau de lecture."""
    art = await db.get(Article, article_id)
    if art is None:
        raise HTTPException(404, "article introuvable")
    _attach_source(art, await db.get(MediaSource, art.media_source_id))
    return art


@router.post("/collect-press", response_model=dict, dependencies=[Depends(require_token)])
async def trigger_press(
    reset: bool = Query(False, description="purge les articles avant de recollecter"),
) -> dict:
    """Run one French-press collection sweep now."""
    stats = await run_press_collection(reset=reset)
    stats["errors"] = len(stats["errors"])
    return stats


@router.post("/archive-press", response_model=dict, dependencies=[Depends(require_token)])
async def trigger_archive(limit: int = Query(50, ge=1, le=500)) -> dict:
    """Archive not-yet-archived press articles (snapshot local + Wayback)."""
    return await run_archival(kind="press", limit=limit)
