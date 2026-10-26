"""Load backend/data/pool_rn_udr.json into the database (idempotent upsert).

    python -m src.scripts.seed_pool
"""

import asyncio
import json

import structlog
from sqlalchemy import select

from src.config import get_settings
from src.database import get_session_factory, init_db
from src.models.personality import Personality

logger = structlog.get_logger(__name__)


async def seed() -> dict:
    settings = get_settings()
    pool = json.loads(settings.pool_path.read_text(encoding="utf-8"))
    entries = pool["personalities"]

    await init_db()
    factory = get_session_factory()
    created = updated = 0

    async with factory() as db:
        for e in entries:
            existing = None
            if e.get("handle"):
                res = await db.execute(
                    select(Personality).where(Personality.handle == e["handle"])
                )
                existing = res.scalar_one_or_none()
            if existing is None:
                res = await db.execute(
                    select(Personality).where(
                        Personality.full_name == e["full_name"],
                        Personality.handle.is_(None),
                    )
                )
                existing = res.scalar_one_or_none()

            fields = dict(
                full_name=e["full_name"],
                handle=e.get("handle"),
                group_code=e["group_code"],
                group_long=e.get("group_long"),
                famille=e.get("famille"),
                role=e.get("role"),
                verif=e.get("verif"),
                circo=e.get("circo"),
                departement=e.get("departement"),
                photo_url=e.get("photo_url"),
                an_id=e.get("an_id"),
            )
            if existing:
                for k, v in fields.items():
                    setattr(existing, k, v)
                updated += 1
            else:
                db.add(Personality(**fields))
                created += 1
        await db.commit()

    stats = {"created": created, "updated": updated, "total": len(entries)}
    logger.info("seed.done", **stats)
    print(f"Seed terminé: {stats}")
    return stats


# Comptes X renommés depuis la constitution du pool : ancien handle -> nouveau.
# `seed` reconnaît une figure à son handle ; sans ce renommage en base, le
# nouveau handle du pool créerait une seconde fiche au lieu de corriger la
# première, et les tweets resteraient rattachés à l'ancienne.
RENOMMES = {
    "MessihaOfficiel": "JeanMessiha",  # 26/10/2026 : 404 sur l'ancien, 322 000 abonnés sur le nouveau
}


async def ensure_renommes() -> dict:
    """Applique `RENOMMES` aux fiches qui portent encore l'ancien handle."""
    factory = get_session_factory()
    faits = {}
    async with factory() as db:
        for ancien, nouveau in RENOMMES.items():
            p = await db.scalar(select(Personality).where(Personality.handle == ancien))
            if p is None or await db.scalar(select(Personality.id).where(Personality.handle == nouveau)):
                continue
            p.handle = nouveau
            # L'audience lue sous l'ancien handle n'était pas la sienne.
            p.followers_count = p.statuses_count = p.x_user_id = None
            faits[ancien] = nouveau
        await db.commit()
    return faits


if __name__ == "__main__":
    asyncio.run(seed())
