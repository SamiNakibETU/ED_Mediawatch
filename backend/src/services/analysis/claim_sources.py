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


async def resolve_claim_sources(
    db: AsyncSession, claims: Iterable[Claim]
) -> dict[int, dict | None]:
    """{claim_id: la source elle-même} : le tweet entier ou l'article, avec son reçu.

    Un lien seul ne suffit pas. Une déclaration se relit dans son contexte, et
    un tweet supprimé ne s'ouvre plus : le texte conservé en base et l'archive
    Wayback sont alors la seule preuve de ce qui a été dit.
    """
    from src.models.personality import Personality

    claims = list(claims)
    post_ids = {c.post_id for c in claims if c.post_id}
    article_ids = {c.article_id for c in claims if c.article_id}

    posts: dict[int, dict] = {}
    if post_ids:
        rows = (await db.execute(
            select(Post, Personality.handle)
            .join(Personality, Personality.id == Post.personality_id)
            .where(Post.id.in_(post_ids))
        )).all()
        for p, handle in rows:
            posts[p.id] = {
                "kind": "tweet", "url": p.url, "text": p.content,
                "published_at": p.published_at, "archive": p.snapshot_url,
                "author": handle, "post_type": p.post_type,
                "quoted_author": p.quoted_handle, "quoted_text": p.quoted_content,
                "truncated": bool(p.text_truncated),
            }
    articles: dict[int, dict] = {}
    if article_ids:
        for a in (await db.execute(select(Article).where(Article.id.in_(article_ids)))).scalars():
            articles[a.id] = {
                "kind": "article", "url": a.url, "title": a.title,
                "published_at": a.published_at, "archive": a.snapshot_url,
                "author": a.media_source_id,
            }
    return {
        c.id: (posts.get(c.post_id) if c.post_id else None)
        or (articles.get(c.article_id) if c.article_id else None)
        for c in claims
    }
