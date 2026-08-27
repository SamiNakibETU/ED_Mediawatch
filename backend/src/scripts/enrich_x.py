"""Texte intégral des tweets tronqués (syndication coupe à 280) via fxtwitter.

    python -m src.scripts.enrich_x          # 400 posts max par passe
    python -m src.scripts.enrich_x 1000

Invalide les déclarations L0 extraites d'un texte coupé (relancer
`extract_declarations` ensuite). Résumable : ne traite que `text_truncated`.
"""

import asyncio
import sys

from src.database import init_db

from src.services.collection.x_enrich import enrich_truncated_posts

if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 400
    async def _main():
        await init_db()
        return await enrich_truncated_posts(limit=n)
    print(asyncio.run(_main()))
