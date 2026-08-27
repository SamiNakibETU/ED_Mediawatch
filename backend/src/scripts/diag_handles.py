"""Diagnostic des handles X muets : introuvable, homonyme probable, ou muet.

Après une passe complète, un handle sans aucun tweet peut être :
  * **introuvable** — compte renommé ou suspendu (fxtwitter : 404) ;
  * **homonyme probable** — le compte existe mais avec une audience dérisoire
    (quelques abonnés) pour une personnalité politique : ce n'est pas elle ;
  * **muet/protégé** — compte réel mais sans tweet public récent.

La distinction compte : les deux premiers sont des erreurs de POOL (données de
référence), pas de collecte. Le diagnostic est écrit dans `last_error` pour
être visible dans /health/collectors.

    python -m src.scripts.diag_handles            # handles sans post
    python -m src.scripts.diag_handles --all      # tout le pool actif
"""

from __future__ import annotations

import asyncio
import sys

import httpx
from sqlalchemy import select

from src.config import get_settings
from src.database import get_session_factory, init_db
from src.models.personality import Personality
from src.models.post import Post

# En dessous, une « personnalité politique suivie » n'est vraisemblablement pas
# le compte visé (homonyme, compte parqué, usurpation).
LOW_AUDIENCE = 500


async def diagnose(handle: str, client: httpx.AsyncClient) -> tuple[str, str]:
    try:
        r = await client.get(f"https://api.fxtwitter.com/{handle}")
    except httpx.HTTPError as exc:
        return "inconnu", f"réseau : {str(exc)[:60]}"
    if r.status_code == 404:
        return "introuvable", "compte renommé ou suspendu (404) — corriger le pool"
    if r.status_code != 200:
        return "inconnu", f"fxtwitter HTTP {r.status_code}"
    u = (r.json() or {}).get("user") or {}
    followers, tweets = u.get("followers") or 0, u.get("tweets") or 0
    if u.get("protected"):
        return "protege", f"compte protégé ({followers} abonnés)"
    if followers < LOW_AUDIENCE:
        return "homonyme", (f"audience dérisoire ({followers} abonnés, {tweets} tweets) : "
                            "probablement pas la bonne personne — corriger le pool")
    if tweets == 0:
        return "muet", f"compte réel ({followers} abonnés) sans aucun tweet"
    return "ok", f"compte réel ({followers} abonnés, {tweets} tweets) — timeline vide en syndication"


async def main() -> None:
    await init_db()
    s = get_settings()
    f = get_session_factory()
    async with f() as db:
        q = select(Personality).where(Personality.handle.isnot(None), Personality.is_active.is_(True))
        if "--all" not in sys.argv:
            q = q.where(Personality.id.notin_(select(Post.personality_id).distinct()))
        people = list((await db.execute(q)).scalars().all())

    counts: dict[str, int] = {}
    async with httpx.AsyncClient(timeout=s.request_timeout_seconds,
                                 headers={"User-Agent": s.user_agent}) as client:
        for p in people:
            verdict, detail = await diagnose(p.handle, client)
            counts[verdict] = counts.get(verdict, 0) + 1
            print(f"  @{p.handle:22s} {p.full_name:28s} {verdict:11s} {detail}")
            async with f() as db:
                obj = await db.get(Personality, p.id)
                if obj is not None and verdict in ("introuvable", "homonyme", "protege"):
                    obj.last_status = verdict[:16]
                    obj.last_error = detail[:200]
                    await db.commit()
            await asyncio.sleep(1.0)
    print("bilan :", counts)


if __name__ == "__main__":
    asyncio.run(main())
