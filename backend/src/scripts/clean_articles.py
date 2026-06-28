"""Re-nettoie le corps des articles déjà stockés (liens + boilerplate) et
recompute `word_count`. Idempotent : rejouable sans effet de bord.

    python -m src.scripts.clean_articles            # tout
    python -m src.scripts.clean_articles --dry       # rapport seul, sans écrire

Sert à appliquer rétroactivement `clean_article_text` au corpus collecté avant
les améliorations (couche de raffinage rejouable, cf ROADMAP §1).
"""

from __future__ import annotations

import asyncio
import sys

import structlog
from sqlalchemy import select

from src.database import get_session_factory, init_db
from src.models.article import Article
from src.services.collection.text_clean import clean_article_text

logger = structlog.get_logger(__name__)


async def run(dry: bool = False) -> dict:
    await init_db()
    factory = get_session_factory()
    changed = removed_chars = scanned = 0

    async with factory() as db:
        ids = list((await db.execute(select(Article.id))).scalars().all())

    for aid in ids:
        async with factory() as db:
            art = await db.get(Article, aid)
            if not art or not art.content:
                continue
            scanned += 1
            cleaned = clean_article_text(art.content)
            if cleaned != art.content:
                removed_chars += max(0, len(art.content) - len(cleaned))
                changed += 1
                if not dry:
                    art.content = cleaned
                    art.word_count = len(cleaned.split())
                    await db.commit()

    stats = {"scanned": scanned, "changed": changed,
             "chars_removed": removed_chars, "dry": dry}
    logger.info("clean_articles.done", **stats)
    print(f"Nettoyage articles: {stats}")
    return stats


if __name__ == "__main__":
    asyncio.run(run(dry="--dry" in sys.argv))
