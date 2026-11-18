"""Fait entrer en base les tweets collectés sur disque, sans passer par le serveur (étape 5 du plan).

La plateforme en ligne étant éteinte, les collecteurs ont écrit leurs tweets dans
``donnees/x-historique`` (recherche) et ``donnees/x-timeline`` (pages de profil). Ce script
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


async def importer(essai: bool) -> dict:
    from src.database import init_db
    from src.services.collection.x_zeeschuimer import importer_lot, normaliser_lot

    await init_db()
    vus: set[str] = set()
    total: dict[str, int] = {}
    for via, dossier in SOURCES.items():
        tweets = lire(dossier, vus)
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
