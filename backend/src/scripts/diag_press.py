"""Audit de la collecte presse, source par source — rend la sélection LISIBLE.

Pour chaque source du pool : flux joignable ? combien d'entrées ? le flux fournit-il
l'ARTICLE COMPLET (content:encoded) ou juste un chapô ? et le ENTONNOIR de sélection
(pertinent RN/ED → prise_de_parole vs mention). Répond à « pourquoi si peu d'articles »
et « comment sont choisis les articles ». Non destructif, aucune écriture en base.

    python -m src.scripts.diag_press                 # depuis une IP résidentielle
    railway ssh "python -m src.scripts.diag_press"   # depuis Railway (voit les 403 datacenter)
"""

import asyncio
import json

import aiohttp
import feedparser

from src.config import BACKEND_DIR, get_settings
from src.services.collection.extractor_client import extract_html
from src.services.collection.press_collector import _rss_full_html
from src.services.collection.relevance import build_index
from src.utils import clean_html
from src.vocabulary import Nature

_FULL_MIN = 1200  # seuil « article complet » dans le flux (cf. _RSS_FULLTEXT_MIN)
_SAMPLE = 30      # entrées examinées par source


async def _audit(http, src, index, sem) -> dict:
    out = {"id": src["id"], "leaning": src["leaning"], "status": None,
           "entries": 0, "full_feed_pct": 0, "avg_chars": 0,
           "relevant": 0, "pdp": 0, "mention": 0, "note": ""}
    ua = get_settings().user_agent
    async with sem:
        try:
            async with http.get(src["rss_url"], headers={"User-Agent": ua},
                                 timeout=aiohttp.ClientTimeout(total=12),
                                 allow_redirects=True) as resp:
                out["status"] = resp.status
                if resp.status != 200:
                    return out
                text = await resp.text()
        except Exception as exc:  # noqa: BLE001
            out["status"] = "ERR"
            out["note"] = str(exc)[:60]
            return out

    feed = feedparser.parse(text)
    entries = feed.entries[: _SAMPLE]
    out["entries"] = len(feed.entries)
    if not entries:
        out["note"] = "0 entrée (bozo)" if feed.bozo else "0 entrée"
        return out

    full = 0
    chars = []
    for e in entries:
        title = clean_html(getattr(e, "title", ""))
        summary = clean_html(getattr(e, "summary", "") if hasattr(e, "get") else "")
        txt = await extract_html(_rss_full_html(e)) or ""
        chars.append(len(txt))
        if len(txt) >= _FULL_MIN:
            full += 1
        v = index.assess(f"{title}. {txt or summary or title}")
        if v["relevant"]:
            out["relevant"] += 1
            out["pdp" if v["nature"] == Nature.PRISE_DE_PAROLE else "mention"] += 1
    out["full_feed_pct"] = round(100 * full / len(entries))
    out["avg_chars"] = round(sum(chars) / len(chars))
    return out


async def main() -> None:
    sources = json.loads((BACKEND_DIR / "data" / "media_sources_fr.json").read_text("utf-8"))["sources"]
    index = build_index([])  # figures_noyau + partis (suffisant pour l'entonnoir)
    sem = asyncio.Semaphore(6)
    async with aiohttp.ClientSession() as http:
        rows = await asyncio.gather(*(_audit(http, s, index, sem) for s in sources))

    print(f"{'source':22} {'lean':10} {'stat':>4} {'ent':>4} {'full%':>5} {'avgc':>6} {'rel':>4} {'pdp':>4} {'men':>4}  note")
    print("-" * 92)
    for r in sorted(rows, key=lambda r: (str(r["status"]) != "200", r["id"])):
        print(f"{r['id']:22} {r['leaning']:10} {str(r['status']):>4} {r['entries']:>4} "
              f"{r['full_feed_pct']:>4}% {r['avg_chars']:>6} {r['relevant']:>4} {r['pdp']:>4} "
              f"{r['mention']:>4}  {r['note']}")
    ok = [r for r in rows if str(r["status"]) == "200"]
    full_feeds = [r["id"] for r in ok if r["full_feed_pct"] >= 50]
    dead = [r["id"] for r in rows if str(r["status"]) != "200"]
    print(f"\nJoignables: {len(ok)}/{len(rows)} · flux full-text (≥50%): {full_feeds}")
    print(f"Mortes/à corriger: {dead}")
    print("Lecture : full%=part d'entrées avec l'article complet dans le flux ; "
          "rel/pdp/men = entonnoir pertinence → prise_de_parole / mention.")


if __name__ == "__main__":
    asyncio.run(main())
