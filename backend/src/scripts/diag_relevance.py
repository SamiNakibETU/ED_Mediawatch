"""Diagnostic : applique le nouveau filtre de pertinence aux articles déjà
stockés et affiche la répartition (prise_de_parole / mention / rejet) + des
exemples. Non destructif. Sert à valider la précision avant re-collecte.

    railway ssh "python -m src.scripts.diag_relevance"
"""

import asyncio

from sqlalchemy import select

from src.database import get_session_factory
from src.models.article import Article
from src.models.personality import Personality
from src.services.collection.relevance import build_index


async def main() -> None:
    factory = get_session_factory()
    async with factory() as db:
        people = [
            p.full_name
            for p in (await db.execute(select(Personality))).scalars().all()
            if (p.famille or "").lower() not in {"officiel", "groupe"}
        ]
        articles = list((await db.execute(select(Article))).scalars().all())

    idx = build_index(people)
    buckets = {"prise_de_parole": [], "mention": [], "reject": []}
    for a in articles:
        v = idx.assess(f"{a.title}. {a.content}")
        key = v["nature"] if v["relevant"] else "reject"
        buckets[key].append((a, v))

    n = len(articles)
    print(f"Articles testés : {n}")
    for k in ("prise_de_parole", "mention", "reject"):
        print(f"  {k:16} : {len(buckets[k]):3}  ({100*len(buckets[k])//max(n,1)}%)")

    for k in ("prise_de_parole", "mention", "reject"):
        print(f"\n--- {k} (3 exemples) ---")
        for a, v in buckets[k][:3]:
            print(f"  [{a.media_source_id}] {a.title[:65]}")
            print(f"     speakers={v['personalities'][:4]} kw={v['keywords'][:3]}")


if __name__ == "__main__":
    asyncio.run(main())
