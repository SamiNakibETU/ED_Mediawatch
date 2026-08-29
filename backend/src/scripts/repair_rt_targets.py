"""Rattrape la cible des relais déjà collectés — retweets et citations.

Le parseur de syndication lisait `retweeted_status` pour en prendre le texte,
mais jetait son auteur : 1 438 retweets sur 1 455 n'avaient aucune cible en
base. Un retweet sans cible n'est pas un signal d'amplification, c'est une ligne
morte — et le graphe d'amplification n'aurait rien eu à relier.

Le parseur est corrigé, mais l'historique ne se répare pas tout seul : la
déduplication par `guid` empêche une nouvelle collecte de réécrire les lignes
existantes. Ce script redemande chaque retweet à fxtwitter par son identifiant,
qui rend le tweet sous son auteur d'ORIGINE — c'est de là que vient la cible.

Les citations souffrent du même mal pour une autre raison : l'ancien parseur
Nitter posait `post_type = "quote"` d'après le HTML sans toujours retrouver
l'auteur cité. Nitter est mort, ses données restent — 826 citations sur 1 037
étaient sans cible. fxtwitter expose `quote.author`, le même passage les
récupère.

    python -m src.scripts.repair_rt_targets              # dit ce qu'il ferait
    python -m src.scripts.repair_rt_targets --apply      # le fait
    python -m src.scripts.repair_rt_targets --apply --limit 200

Rythme poli : en série, avec le délai de configuration. fxtwitter n'est pas à
nous, et 1 400 requêtes d'un coup seraient un abus. Reprenable : relancer ne
retraite que ce qui manque encore.
"""

import asyncio
import sys

import httpx
import structlog
from sqlalchemy import select

from src.config import get_settings
from src.database import get_session_factory, init_db
from src.models.post import Post
from src.services.collection.x_backfill import fetch_tweet
from src.utils import status_id

logger = structlog.get_logger(__name__)

# Retweets ET citations : les deux portent une cible, et les deux en
# manquaient — pour deux raisons différentes.
RELAYS = ("retweet", "quote")


def _arg(name: str, default: int) -> int:
    if name in sys.argv:
        try:
            return int(sys.argv[sys.argv.index(name) + 1])
        except (IndexError, ValueError):
            pass
    return default


async def main() -> None:
    apply = "--apply" in sys.argv
    limit = _arg("--limit", 500)

    await init_db()
    s = get_settings()
    factory = get_session_factory()

    async with factory() as db:
        todo = list((await db.execute(
            select(Post.id, Post.url)
            .where(Post.post_type.in_(RELAYS), Post.quoted_handle.is_(None))
            .order_by(Post.published_at.desc().nullslast())
            .limit(limit)
        )).all())
        total = len(list((await db.execute(
            select(Post.id).where(Post.post_type.in_(RELAYS), Post.quoted_handle.is_(None))
        )).all()))

    print(f"\nRetweets sans cible : {total}")
    print(f"Traités dans cette passe : {len(todo)} (--limit {limit})")
    if not todo:
        print("\nRien à faire.\n")
        return
    if not apply:
        print("\nRelance avec --apply. Compter environ "
              f"{len(todo) * s.request_delay_seconds / 60:.0f} min "
              "au rythme de politesse configuré.\n")
        return

    headers = {"User-Agent": s.user_agent, "Accept": "application/json"}
    repaired = gone = 0
    async with httpx.AsyncClient(timeout=s.request_timeout_seconds, headers=headers,
                                 follow_redirects=True) as client:
        for pid, url in todo:
            tid = status_id(url)
            handle = (url or "").split("/status/")[0].rsplit("/", 1)[-1]
            data = await fetch_tweet(client, handle, tid) if tid else None
            await asyncio.sleep(s.request_delay_seconds)
            if not data or not data.get("quoted_handle"):
                # Supprimé, privé, ou compte d'origine fermé. On n'insiste pas :
                # une cible inventée serait pire qu'une cible absente.
                gone += 1
                continue
            async with factory() as db:
                post = await db.get(Post, pid)
                if post is None or post.quoted_handle:
                    continue
                post.quoted_handle = data["quoted_handle"]
                post.quoted_url = data.get("quoted_url")
                await db.commit()
                repaired += 1

    print(f"\nCibles retrouvées : {repaired}")
    print(f"Introuvables (supprimé, privé, compte fermé) : {gone}")
    print(f"Restant après cette passe : {total - repaired}\n")
    logger.info("repair_rt.done", repaired=repaired, gone=gone, remaining=total - repaired)


if __name__ == "__main__":
    asyncio.run(main())
