"""Sonde des instances Nitter : laquelle sert le HTML AVEC engagement (likes/RT) ?

À lancer **depuis la machine qui collectera** (IP résidentielle de préférence ;
une IP datacenter type Railway est souvent bloquée par les instances, comme la
presse). Affiche, par instance : RSS ok ? HTML timeline ? compteurs d'engagement ?

    python -m src.scripts.probe_nitter                 # instances de la config
    python -m src.scripts.probe_nitter https://twitt.re https://autre  # + des extras

Une fois l'instance gagnante trouvée, la fixer :
    NITTER_INSTANCES=https://celle_qui_marche   (ou NITTER_SELF_HOSTED=...)
"""

from __future__ import annotations

import asyncio
import sys

import aiohttp

from src.config import get_settings

SAMPLE_HANDLE = "J_Bardella"


async def _probe(http: aiohttp.ClientSession, base: str) -> dict:
    base = base.rstrip("/")
    o: dict = {"inst": base, "rss": False, "html": False, "engagement": False, "err": ""}
    try:
        async with http.get(
            f"{base}/{SAMPLE_HANDLE}",
            timeout=aiohttp.ClientTimeout(total=20), allow_redirects=True, ssl=False,
        ) as r:
            t = await r.text() if r.status == 200 else ""
            o["status"] = r.status
            if "timeline-item" in t and len(t) > 2000:
                o["html"] = True
                o["engagement"] = "tweet-stat" in t and "icon-heart" in t
    except Exception as exc:  # noqa: BLE001
        o["err"] = f"{type(exc).__name__}:{str(exc)[:40]}"
    try:
        async with http.get(
            f"{base}/{SAMPLE_HANDLE}/rss",
            timeout=aiohttp.ClientTimeout(total=15), ssl=False,
        ) as r:
            tt = await r.text() if r.status == 200 else ""
            o["rss"] = tt[:120].lstrip().lower().startswith("<?xml")
    except Exception:  # noqa: BLE001
        pass
    return o


async def main() -> None:
    extra = [a for a in sys.argv[1:] if a.startswith("http")]
    instances = list(dict.fromkeys(get_settings().nitter_instance_list + extra))
    headers = {"User-Agent": get_settings().user_agent,
               "Accept-Language": "fr-FR,fr;q=0.9"}
    conn = aiohttp.TCPConnector(ssl=False)
    winners: list[str] = []
    async with aiohttp.ClientSession(headers=headers, connector=conn) as http:
        for base in instances:
            o = await _probe(http, base)
            tag = ("ENGAGEMENT" if o["engagement"]
                   else "HTML-no-eng" if o["html"] else "no-html  ")
            print(f"{tag:12} rss={'Y' if o['rss'] else 'n'}  {o['inst']:38} "
                  f"{o.get('err','')}")
            if o["engagement"]:
                winners.append(o["inst"])
    print()
    if winners:
        print("ENGAGEMENT dispo via :", ", ".join(winners))
        print(f"→ NITTER_INSTANCES={winners[0]}")
    else:
        print("Aucune instance ne sert l'engagement depuis cette IP.")
        print("→ soit relancer ailleurs (IP résidentielle), soit self-host "
              "(NITTER_SELF_HOSTED, cf infra/docker-compose.nitter.yml).")


if __name__ == "__main__":
    asyncio.run(main())
