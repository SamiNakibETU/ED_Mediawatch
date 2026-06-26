"""Load backend/data/media_sources_fr.json into the database (idempotent).

    python -m src.scripts.seed_media
"""

import asyncio
import json

import structlog

from src.config import BACKEND_DIR
from src.database import get_session_factory, init_db
from src.models.media_source import MediaSource

logger = structlog.get_logger(__name__)
MEDIA_FILE = BACKEND_DIR / "data" / "media_sources_fr.json"


async def seed() -> dict:
    data = json.loads(MEDIA_FILE.read_text(encoding="utf-8"))
    sources = data["sources"]

    await init_db()
    factory = get_session_factory()
    created = updated = 0
    async with factory() as db:
        for s in sources:
            existing = await db.get(MediaSource, s["id"])
            fields = dict(
                name=s["name"],
                homepage=s.get("homepage"),
                rss_url=s["rss_url"],
                category=s.get("category", "national"),
                leaning=s.get("leaning", "center"),
                is_active=s.get("is_active", True),  # sources mortes : is_active=false
            )
            if existing:
                for k, v in fields.items():
                    setattr(existing, k, v)
                updated += 1
            else:
                db.add(MediaSource(id=s["id"], **fields))
                created += 1
        await db.commit()

    stats = {"created": created, "updated": updated, "total": len(sources)}
    logger.info("seed_media.done", **stats)
    print(f"Seed médias terminé: {stats}")
    return stats


if __name__ == "__main__":
    asyncio.run(seed())
