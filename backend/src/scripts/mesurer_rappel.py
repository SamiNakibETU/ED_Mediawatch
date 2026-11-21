"""Ce que les mots-clés font rater : lit un échantillon de tweets qu'aucun mot-clé d'enjeu n'a retenus.

Le registre ne lit que les tweets où un mot-clé d'enjeu apparaît (environ 10 000 sur 115 000). Si
les autres contiennent des positions sur les enjeux, le registre en perd. On tire au hasard des tweets
non lus, sans mot-clé, et on les fait lire comme les autres ; la part qui porte une position sur un
enjeu, rapportée au nombre de tweets non lus, estime la perte. Les déclarations trouvées entrent au
registre comme les autres.

    python -m src.scripts.mesurer_rappel [--n 1000]
"""

from __future__ import annotations

import argparse
import asyncio
import os
import random
import re
import sys

os.environ.setdefault("SCHEDULER_ENABLED", "false")
GRAINE = 20261121


async def main_async(n: int) -> int:
    from sqlalchemy import func, or_, select

    from src.database import get_session_factory, init_db
    from src.models.declaration import Declaration
    from src.models.post import Post
    from src.scripts.atelier_enjeux import MOTS
    from src.scripts.lire_registre import passer
    from src.services.analysis.registre import VERSION, pretri

    await init_db()
    motif = re.compile("|".join(f"(?:{m})" for m in MOTS.values()), re.IGNORECASE)
    factory = get_session_factory()
    async with factory() as db:
        posts = (await db.execute(
            select(Post).where(or_(Post.decl_lu.is_(None), ~Post.decl_lu.startswith(VERSION))))).scalars().all()
    candidats = [p.id for p in posts if p.content and not motif.search(p.content) and pretri(p) is None]
    print(f"{len(posts)} tweets non lus, dont {len(candidats)} sans mot-clé et lisibles.", flush=True)
    echantillon = random.Random(GRAINE).sample(candidats, min(n, len(candidats)))
    total = await passer(echantillon, None)
    async with factory() as db:
        rows = (await db.execute(
            select(Declaration.enjeu, func.count()).where(
                Declaration.post_id.in_(echantillon), Declaration.position.isnot(None),
                or_(Declaration.douteuse.is_(None), Declaration.douteuse.is_(False)))
            .group_by(Declaration.enjeu))).all()
        touches = await db.scalar(select(func.count(func.distinct(Declaration.post_id))).where(
            Declaration.post_id.in_(echantillon), Declaration.position.isnot(None)))
    sur_enjeu = sum(c for _, c in rows)
    part = (touches or 0) / max(1, len(echantillon))
    print(f"\nÉchantillon : {len(echantillon)} tweets. {touches} portent une position sur un enjeu "
          f"({part:.1%}), {sur_enjeu} déclarations en tout. Par enjeu : {sorted(rows, key=lambda r: -r[1])}", flush=True)
    print(f"Estimation sur les {len(candidats)} tweets sans mot-clé : environ {round(part * len(candidats))} "
          f"tweets portant une position que le registre ne lit pas.", flush=True)
    print(f"Lecture : {total}", flush=True)
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--n", type=int, default=1000)
    a = p.parse_args()
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    return asyncio.run(main_async(a.n))


if __name__ == "__main__":
    raise SystemExit(main())
