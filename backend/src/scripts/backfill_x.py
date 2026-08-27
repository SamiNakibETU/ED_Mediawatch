"""Backfill X historique SANS compte : Wayback CDX (identifiants) + fxtwitter (contenu).

Remplace l'ancien backfill par pagination HTML Nitter (mort depuis la mise en
demeure du 24/08/2026). Résumable : dédup par guid, un identifiant déjà en base
n'est jamais re-demandé. Rythme poli (série + délai) — fxtwitter n'est pas à nous.

    python -m src.scripts.backfill_x                       # tout le pool, depuis 2022
    python -m src.scripts.backfill_x 2024                  # depuis une autre année
    python -m src.scripts.backfill_x 2022 MLP_officiel J_Bardella   # handles ciblés

Bornes par défaut : 300 identifiants par handle, 2000 tweets par run — relancer
pour continuer (ne reprend que ce qui manque).
"""

import asyncio
import sys

from src.database import init_db

from src.services.collection.x_backfill import run_backfill


async def main() -> None:
    # Schéma à jour (colonnes additives) même hors démarrage de l'app.
    await init_db()
    args = sys.argv[1:]
    since_year = int(args[0]) if args and args[0].isdigit() else 2022
    handles = [a.lstrip("@") for a in args[1:]] if len(args) > 1 else None
    stats = await run_backfill(handles=handles, since_year=since_year)
    print("Backfill terminé:", {k: v for k, v in stats.items() if k != "per_handle"})
    for h, n in sorted(stats["per_handle"].items(), key=lambda kv: -kv[1])[:15]:
        print(f"  {h:24s} +{n}")


if __name__ == "__main__":
    asyncio.run(main())
