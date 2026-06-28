"""Découvre + valide les flux RSS des titres de `aide/medias_francais.csv`.

But (C2) : passer de ~28 à 60-85 sources presse (spectre complet + PQR), sans
saisie manuelle. Pour chaque titre absent du catalogue actuel, on teste quelques
patterns RSS usuels, on VALIDE (feedparser parse + entrées datées), et on écrit
les candidats trouvés dans `data/media_candidates.json` (à relire puis fusionner
dans `media_sources_fr.json`).

Minimal par design : réutilise feedparser + aiohttp (déjà là), aucune dépendance
nouvelle. Lecture seule du web, poli (UA navigateur, concurrence bornée).

Usage : python -m src.scripts.discover_rss
"""

from __future__ import annotations

import asyncio
import csv
import json
from urllib.parse import urlparse

import aiohttp
import feedparser

from src.config import BACKEND_DIR, get_settings
from src.utils import slugify

CSV_PATH = BACKEND_DIR.parent / "aide" / "medias_francais.csv"
CATALOG_PATH = BACKEND_DIR / "data" / "media_sources_fr.json"
OUT_PATH = BACKEND_DIR / "data" / "media_candidates.json"

# Patterns RSS les plus courants (testés dans l'ordre, on garde le 1er valide).
RSS_PATTERNS = [
    "/rss", "/feed", "/feed/", "/rss.xml", "/rss/une.xml", "/rss/une",
    "/feeds/rss-une.xml", "/spip.php?page=backend", "/?feed=rss2",
    "/arc/outboundfeeds/rss/?outputType=xml",
]


def _leaning(orientation: str) -> str:
    o = orientation.lower()
    if any(k in o for k in ("extreme droite", "extreme-droite", "droite radicale",
                            "nouvelle droite", "proche extreme droite", "agregateur extreme")):
        return "far_right"
    if "extreme gauche" in o or "gauche radicale" in o or "gauche communiste" in o:
        return "far_left"
    if "droite" in o:
        return "right"
    if "gauche" in o:
        return "left"
    return "center"


def _category(type_: str, perimetre: str) -> str:
    if "regional" in perimetre.lower():
        return "regional"
    t = type_.lower()
    if "pure player" in t:
        return "pure_player"
    if any(k in t for k in ("hebdo", "mensuel", "revue", "magazine")):
        return "magazine"
    return "national"


def _domain(url: str) -> str:
    return (urlparse(url).hostname or "").replace("www.", "")


def _existing_domains() -> set[str]:
    cat = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    return {_domain(s.get("homepage") or s.get("rss_url", "")) for s in cat["sources"]}


def _candidates_from_csv(skip: set[str]) -> list[dict]:
    rows: list[dict] = []
    with CSV_PATH.open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            url = (r.get("url") or "").strip()
            if not url.startswith("http"):
                continue  # « (pas de site) »
            if _domain(url) in skip:
                continue
            rows.append({
                "id": slugify(r["nom"]),
                "name": r["nom"].strip(),
                "homepage": url.rstrip("/"),
                "category": _category(r.get("type", ""), r.get("perimetre", "")),
                "leaning": _leaning(r.get("orientation_indicative", "")),
            })
    return rows


async def _try_feed(http: aiohttp.ClientSession, base: str, path: str) -> str | None:
    url = base + path
    try:
        async with http.get(url, timeout=aiohttp.ClientTimeout(total=8),
                            allow_redirects=True) as resp:
            if resp.status != 200:
                return None
            body = await resp.text()
    except Exception:  # noqa: BLE001
        return None
    feed = feedparser.parse(body)
    return url if len(feed.entries) >= 3 else None


async def _discover_one(http: aiohttp.ClientSession, cand: dict, sem: asyncio.Semaphore) -> dict:
    async with sem:
        for path in RSS_PATTERNS:
            found = await _try_feed(http, cand["homepage"], path)
            if found:
                return {**cand, "rss_url": found, "status": "ok"}
        return {**cand, "rss_url": None, "status": "not_found"}


async def main() -> None:
    skip = _existing_domains()
    cands = _candidates_from_csv(skip)
    print(f"{len(cands)} titres à découvrir (hors {len(skip)} déjà présents)")

    headers = {"User-Agent": get_settings().user_agent}
    sem = asyncio.Semaphore(8)
    async with aiohttp.ClientSession(headers=headers) as http:
        results = await asyncio.gather(*(_discover_one(http, c, sem) for c in cands))

    ok = [r for r in results if r["status"] == "ok"]
    OUT_PATH.write_text(
        json.dumps({"found": ok, "missing": [r["name"] for r in results if r["status"] != "ok"]},
                   ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"trouvés : {len(ok)} / {len(cands)}  -> {OUT_PATH}")
    for r in ok:
        print(f"  + {r['leaning']:<10} {r['category']:<11} {r['name']} -> {r['rss_url']}")
    miss = [r['name'] for r in results if r['status'] != 'ok']
    if miss:
        print(f"non trouvés ({len(miss)}) : {', '.join(miss)}")


if __name__ == "__main__":
    asyncio.run(main())
