"""Backfill X depuis une date (défaut : 2026-05-01) via pagination HTML Nitter.

Nécessite une source HTML qui sert la timeline (Nitter auto-hébergé en pratique
— configurer NITTER_SELF_HOSTED). Résumable : la dédup par guid fait qu'un
re-run ne récupère que ce qui manque.

    python -m src.scripts.backfill_x                # depuis 2026-05-01
    python -m src.scripts.backfill_x 2025-09-01     # depuis une autre date
"""

import asyncio
import sys
from datetime import datetime, timezone

from src.services.collection.x_collector import run_backfill

DEFAULT_SINCE = "2026-05-01"


async def main() -> None:
    since_str = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_SINCE
    since = datetime.fromisoformat(since_str).replace(tzinfo=timezone.utc)
    stats = await run_backfill(since)
    print("Backfill terminé:", stats)
    if stats["blocked"] == stats["handles"]:
        print(
            "\n⚠️  Toutes les requêtes HTML ont échoué : aucune instance Nitter ne sert\n"
            "    la timeline. Configure un Nitter auto-hébergé (NITTER_SELF_HOSTED),\n"
            "    voir docker-compose.nitter.yml."
        )


if __name__ == "__main__":
    asyncio.run(main())
