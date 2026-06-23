"""Résolution claim → URL de la source (post X ou article presse).

Provenance : un claim renvoie toujours à son origine vérifiable (le tweet ou
l'article). Lookup groupé pour éviter le N+1.
"""

from __future__ import annotations

from collections.abc import Iterable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.article import Article
from src.models.claim import Claim
from src.models.post import Post


async def resolve_claim_urls(
    db: AsyncSession, claims: Iterable[Claim]
) -> dict[int, str | None]:
    """{claim_id: source_url} pour une liste de claims."""
    claims = list(claims)
    post_ids = {c.post_id for c in claims if c.post_id}
    article_ids = {c.article_id for c in claims if c.article_id}

    post_url: dict[int, str] = {}
    if post_ids:
        post_url = dict(
            (await db.execute(select(Post.id, Post.url).where(Post.id.in_(post_ids)))).all()
        )
    article_url: dict[int, str] = {}
    if article_ids:
        article_url = dict(
            (await db.execute(select(Article.id, Article.url).where(Article.id.in_(article_ids)))).all()
        )

    return {
        c.id: (post_url.get(c.post_id) if c.post_id else None)
        or (article_url.get(c.article_id) if c.article_id else None)
        for c in claims
    }
