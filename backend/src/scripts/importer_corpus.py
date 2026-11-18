"""Fait entrer en base les tweets collectés sur disque, sans passer par le serveur (étape 5 du plan).

La plateforme en ligne étant éteinte, les collecteurs ont écrit leurs tweets dans
``donnees/x-historique`` (recherche), ``donnees/x-timeline`` (pages de profil) et, pour les
comptes de recherche, ``donnees/x-comptes/corpus.db`` (mediascrapers). Ce script
les importe par la même fonction que la route ``/collect/tweets`` (``importer_lot``) :
mêmes règles, seuls les comptes suivis entrent, un tweet déjà en base n'est pas doublé.

Pas de serveur : son planificateur lancerait une collecte Nitter en parallèle de celle qui
tourne (une seule à la fois par instance).

    python -m src.scripts.importer_corpus [--essai]
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

ETUDE = Path(__file__).resolve().parents[4]
SOURCES = {"xitter": ETUDE / "donnees" / "x-historique", "xitter-p": ETUDE / "donnees" / "x-timeline"}
LOT = 500


def lire(dossier: Path, vus: set[str]) -> list[dict]:
    out = []
    for f in sorted(dossier.glob("*.ndjson")):
        for ligne in f.read_text(encoding="utf-8").splitlines():
            try:
                t = json.loads(ligne)
            except ValueError:          # ligne en cours d'écriture
                continue
            url = str(t.get("url") or "")
            if not url.startswith("https://x.com/") or url in vus:
                continue
            vus.add(url)
            t.setdefault("auteur", url.split("/")[3])
            t.pop("mois", None)
            out.append(t)
    return out


COMPTES = ETUDE / "donnees" / "x-comptes" / "corpus.db"
CHAMPS = ("url", "published_at", "post_type", "lang", "reply_to_handle", "quoted_handle", "quoted_url",
          "likes", "retweets", "replies", "quotes", "views", "text_truncated")


def lire_comptes(vus: set[str]) -> list[dict]:
    """Les tweets rapportés par les comptes de recherche (mediascrapers, projet « ed-mediawatch »)."""
    import sqlite3

    if not COMPTES.exists():
        return []
    c = sqlite3.connect(f"file:{COMPTES.as_posix()}?mode=ro", uri=True)
    c.row_factory = sqlite3.Row
    out = []
    for r in c.execute("select * from posts where post_type != 'retweet'"):
        url = (r["url"] or "").replace("https://twitter.com/", "https://x.com/")
        if not url.startswith("https://x.com/") or url in vus or not r["text"]:
            continue
        vus.add(url)
        t = {k: r[k] for k in CHAMPS if k in r.keys()}
        t.update(url=url, auteur=r["handle"], content=r["text"], quoted_content=r["quoted_text"],
                 is_retweet=False, is_reply=r["post_type"] == "reply", text_truncated=bool(r["text_truncated"]))
        out.append(t)
    return out


async def importer(essai: bool) -> dict:
    from src.database import init_db
    from src.services.collection.x_zeeschuimer import importer_lot, normaliser_lot

    await init_db()
    vus: set[str] = set()
    total: dict[str, int] = {}
    for via, dossier in [*SOURCES.items(), ("comptes", None)]:
        tweets = lire(dossier, vus) if dossier else lire_comptes(vus)
        total[f"{via}:lus"] = len(tweets)
        if essai:
            continue
        for i in range(0, len(tweets), LOT):
            r = await importer_lot(normaliser_lot(tweets[i:i + LOT], via))
            for k, v in r.items():
                if isinstance(v, int):
                    total[f"{via}:{k}"] = total.get(f"{via}:{k}", 0) + v
        print(via, {k: v for k, v in total.items() if k.startswith(via)}, flush=True)
    return total


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--essai", action="store_true", help="compter sans écrire")
    print(asyncio.run(importer(p.parse_args().essai)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
