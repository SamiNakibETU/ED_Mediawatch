"""Archive sur Wayback les tweets qui portent une déclaration, les écarts retenus d'abord.

Un tweet supprimé fait disparaître la preuve d'un écart. Pour chaque tweet pas encore archivé :
1. une capture existante de la page x.com, si Wayback en a une (rapide) ;
2. sinon, une capture neuve de la page du tweet sur xitter.cf. Wayback refuse depuis novembre 2026 de
   capturer x.com (réponse 523) ; la page Nitter, elle, est du HTML simple qui garde le texte du tweet.

Ordre : tweets des écarts retenus, puis des mouvements faibles, puis de toutes les déclarations à position.
Une capture à la fois, pause entre deux ; arrêt après plusieurs refus de suite. Relancer reprend où on en est.

    python -m src.scripts.archiver_preuves [--limit 200] [--essai]
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import time
from datetime import datetime, timezone
from urllib.parse import urlparse

os.environ.setdefault("SCHEDULER_ENABLED", "false")

MIROIR = "https://xitter.cf"
SAVE = "https://web.archive.org/save/"
PAUSE_DISPO = 1.5
PAUSE_CAPTURE = 8.0
REFUS_MAX = 4


def chemin(url: str) -> str | None:
    p = urlparse(url or "").path
    return p if "/status/" in p else None


async def capturer(session, url: str) -> tuple[str | None, int]:
    """Save Page Now sans compte. Rend (adresse de la capture, code HTTP)."""
    import aiohttp

    try:
        async with session.get(SAVE + url, allow_redirects=False,
                               timeout=aiohttp.ClientTimeout(total=120, connect=15)) as r:
            loc = r.headers.get("location") or r.headers.get("Content-Location") or ""
            if loc.startswith("/web/"):
                loc = "https://web.archive.org" + loc
            return (loc if "/web/" in loc else None), r.status
    except (asyncio.TimeoutError, aiohttp.ClientError):
        return None, 0


async def file_d_attente(db, limit: int) -> list[tuple[int, str]]:
    from sqlalchemy import text

    rows = (await db.execute(text("""
        with rang as (
          select d.post_id as id, min(case e.auto when 'retenu' then 0 when 'faible' then 1 else 2 end) as r
          from declarations d left join ecarts e on d.id in (e.decl_a_id, e.decl_b_id)
          where d.position is not null and (d.douteuse is null or d.douteuse = 0)
          group by d.post_id)
        select p.id, p.url from posts p join rang on rang.id = p.id
        where p.snapshot_url is null
        order by rang.r, p.published_at desc
        limit :n"""), {"n": limit})).all()
    return [(i, u) for i, u in rows]


async def enregistrer(factory, Post, pid: int, adresse: str) -> None:
    """Écrit l'adresse de la capture. Une autre passe peut tenir la base (21/11/2026 : l'import des scrutins,
    « database is locked ») : on réessaie quelques fois au lieu de perdre la capture et de s'arrêter."""
    from sqlalchemy.exc import OperationalError

    for essai in range(6):
        try:
            async with factory() as db:
                post = await db.get(Post, pid)
                post.snapshot_url, post.archived_at = adresse, datetime.now(timezone.utc)
                await db.commit()
            return
        except OperationalError as exc:
            if "locked" not in str(exc) or essai == 5:
                raise
            await asyncio.sleep(30 * (essai + 1))


async def main_async(limit: int, essai: bool) -> int:
    import aiohttp

    from src.database import get_session_factory, init_db
    from src.models.post import Post
    from src.services.archive.wayback_availability import fetch_wayback_availability

    await init_db()
    factory = get_session_factory()
    async with factory() as db:
        file = await file_d_attente(db, limit)
    print(f"{len(file)} tweets à archiver.", flush=True)
    if essai:
        return 0

    stats = {"existantes": 0, "capturees": 0, "echecs": 0}
    refus, t0 = 0, time.monotonic()
    headers = {"User-Agent": "ED-Mediawatch/1.0 (archivage de recherche, Terra Nova Jeunes)"}
    async with aiohttp.ClientSession(headers=headers) as session:
        for n, (pid, url) in enumerate(file, 1):
            p = chemin(url)
            if p is None:
                stats["echecs"] += 1
                continue
            dispo = await fetch_wayback_availability("https://x.com" + p)
            adresse = dispo.get("closest_url")
            if adresse:
                stats["existantes"] += 1
                await asyncio.sleep(PAUSE_DISPO)
            else:
                adresse, code = await capturer(session, MIROIR + p)
                if adresse:
                    stats["capturees"] += 1
                    refus = 0
                else:
                    stats["echecs"] += 1
                    refus += 1
                    print(f"   refus {code} pour {p}", flush=True)
                    if refus >= REFUS_MAX:
                        print("Arrêt : Wayback refuse plusieurs captures de suite. Relancer plus tard.", flush=True)
                        break
                    await asyncio.sleep(PAUSE_CAPTURE * (2 if code in (429, 0) else 1))
                await asyncio.sleep(PAUSE_CAPTURE)
            if adresse:
                await enregistrer(factory, Post, pid, adresse)
            if n % 25 == 0:
                print(f"{n}/{len(file)} : {stats} en {int((time.monotonic() - t0) / 60)} min", flush=True)
    print(f"Terminé : {stats} en {int((time.monotonic() - t0) / 60)} min.", flush=True)
    return 0 if stats["echecs"] < max(5, len(file) // 5) else 1


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--limit", type=int, default=5000)
    p.add_argument("--essai", action="store_true", help="compte seulement")
    a = p.parse_args()
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    return asyncio.run(main_async(a.limit, a.essai))


if __name__ == "__main__":
    raise SystemExit(main())
