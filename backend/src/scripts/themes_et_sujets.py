"""Thème de chaque tweet, vecteurs des tweets récents, sujets des dernières semaines.

Ce sont les trois étapes dont dépendent les pages Thèmes et Revue. Sur le serveur, le pipeline
les faisait par passes de 4 000 tweets ; ici on les mène jusqu'au bout, en reprenant où on en est.

    python -m src.scripts.themes_et_sujets                      # tout
    python -m src.scripts.themes_et_sujets --themes 400         # essai : 400 tweets, puis s'arrête
    python -m src.scripts.themes_et_sujets --themes 0 --semaines 12   # sujets seulement

Les thèmes vont du plus récent au plus ancien. Les vecteurs ne servent qu'aux sujets de la semaine :
on ne vectorise que les tweets des semaines demandées, pas tout l'historique.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import time
from datetime import datetime, timedelta, timezone

os.environ.setdefault("SCHEDULER_ENABLED", "false")


async def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--themes", type=int, default=-1, help="nombre de tweets à classer (-1 : tous, 0 : aucun)")
    p.add_argument("--semaines", type=int, default=12, help="semaines dont on calcule les sujets (0 : aucune)")
    p.add_argument("--lot", type=int, default=2000, help="tweets par passe")
    a = p.parse_args()
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    from sqlalchemy import func, select

    from src.database import get_session_factory, init_db
    from src.models import Post
    from src.services.analysis.themes import classer, sujets_de_la_semaine, vectoriser

    await init_db()
    t0 = time.monotonic()

    reste = a.themes
    total = {"classes": 0, "vides": 0, "echecs": 0}
    while reste != 0:
        r = await classer(limit=a.lot if reste < 0 else min(a.lot, reste))
        faits = r["classes"] + r["vides"]
        for k in total:
            total[k] += r[k]
        print(f"thèmes : {total} en {int((time.monotonic() - t0) / 60)} min", flush=True)
        if r["budget_atteint"]:
            print("Plafond de dépense atteint : arrêt. Relancer demain reprend ici.", flush=True)
            return 2
        if faits == 0:
            # Plus rien à classer, ou une passe entière en échec : inutile d'insister.
            break
        if reste > 0:
            reste = max(0, reste - faits - r["echecs"])

    if a.semaines > 0:
        debut = datetime.now(timezone.utc) - timedelta(days=7 * a.semaines + 7)
        factory = get_session_factory()
        async with factory() as db:
            n = (await db.execute(select(func.count(Post.id)).where(Post.published_at >= debut))).scalar_one()
        v = await vectoriser(limit=n)
        print(f"vecteurs : {v}", flush=True)
        now = datetime.now(timezone.utc)
        for k in range(a.semaines):
            s = await sujets_de_la_semaine(now - timedelta(days=7 * k))
            print(f"sujets : {s}", flush=True)
    print(f"Terminé en {int((time.monotonic() - t0) / 60)} min.", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
