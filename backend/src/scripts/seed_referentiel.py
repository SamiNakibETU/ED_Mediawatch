"""Charge data/referentiel.json en base (idempotent, versionné).

    python -m src.scripts.seed_referentiel
"""

import asyncio
import json

import structlog

from src.config import BACKEND_DIR
from src.database import get_session_factory, init_db
from src.models.referentiel import Referent, Subtheme, Theme

logger = structlog.get_logger(__name__)
FILE = BACKEND_DIR / "data" / "referentiel.json"


async def seed() -> dict:
    data = json.loads(FILE.read_text(encoding="utf-8"))
    version = data["version"]

    await init_db()
    factory = get_session_factory()
    n_themes = n_subs = n_refs = 0

    async with factory() as db:
        for t in data["themes"]:
            theme = await db.get(Theme, t["id"]) or Theme(id=t["id"])
            theme.label, theme.order, theme.version = t["label"], t.get("order", 0), version
            await db.merge(theme)
            n_themes += 1
            for st in t["subthemes"]:
                sub = Subtheme(id=st["id"], theme_id=t["id"], label=st["label"])
                await db.merge(sub)
                n_subs += 1
                for r in st["referents"]:
                    ref = Referent(
                        key=r["key"], subtheme_id=st["id"], label=r["label"],
                        unit=r.get("unit", ""), version=version,
                    )
                    await db.merge(ref)
                    n_refs += 1
        await db.commit()

    stats = {"version": version, "themes": n_themes, "subthemes": n_subs, "referents": n_refs}
    logger.info("seed_referentiel.done", **stats)
    print(f"Référentiel chargé: {stats}")
    return stats


if __name__ == "__main__":
    asyncio.run(seed())
