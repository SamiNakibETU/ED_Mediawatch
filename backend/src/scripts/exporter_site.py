"""Exporte la plateforme en site statique pour Cloudflare Pages (hébergement sans serveur).

Le serveur de production s'est éteint (Railway, novembre 2026). Plutôt que d'en louer un, on
calcule tout sur le poste de Sami, comme pour Mot de la semaine, et on publie des fichiers :

- les pages (`static/`) telles quelles, marquées ``data-statique="1"`` ;
- chaque réponse de l'API que les pages demandent, enregistrée dans ``api/<clé>.json``.
  La clé est le chemin demandé, requête comprise, avec ses caractères spéciaux codés
  (même fonction ``cle`` ici et dans ``common.js``) ;
- une fonction Cloudflare (``infra/pages/functions/decision.js``, déployée par ``publier_site``) qui reçoit les décisions des relecteurs
  et les garde dans un espace KV ; ``rapatrier_decisions`` les ramène en base chaque semaine.

Ce qui ne se fige pas : les recherches libres et le détail d'un moment cliqué dans la série des
thèmes. La page le dit au lieu d'afficher une erreur.

L'API est appelée dans le processus (``httpx.ASGITransport``) : pas de serveur, donc pas de
planificateur qui collecterait en parallèle de la collecte en cours.

    python -m src.scripts.exporter_site [--sortie ../../site]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import shutil
from pathlib import Path
from urllib.parse import quote, quote_plus

os.environ.setdefault("SCHEDULER_ENABLED", "false")

BACKEND = Path(__file__).resolve().parents[2]
STATIC = BACKEND / "static"
SORTIE = BACKEND.parent / "site"

FIXES = [
    "/enjeux", "/enjeux/etat", "/enjeux/recentes?limit=10", "/ecarts/faits?juge=retenu&limit=3&offset=0",
    "/figures", "/ecarts/compte", "/ecarts/divergences?jours=365", "/revue", "/themes/tree", "/themes/sujets",
    "/etat", "/coherence", "/votes/dissidences?limit=12", "/enjeux/recherche",
]
STATUTS = ["retenu", "faible", "ecarte", "attente"]                 # ecarts.js
TYPES = ["", "temps", "programme", "parti", "chiffre"]
PAS = ["heure", "jour", "semaine", "mois"]                           # themes.js
VUES = ["familles", "themes", "marqueurs"]
PARTIS = ["", "RN", "UDR", "FIGURE"]
PAGE_FIGURE = 60                                                     # figure.js
PAGE_ECARTS = 20


def cle(chemin: str) -> str:
    """Nom de fichier d'un chemin d'API. Doit rendre la même chose que `cle()` dans common.js."""
    return re.sub(r"[^A-Za-z0-9.-]", lambda m: "_" + format(ord(m.group()), "02x"), chemin.lstrip("/"))


class Export:
    def __init__(self, client, dossier: Path):
        self.c, self.dossier, self.ecrits, self.erreurs = client, dossier, 0, []

    async def get(self, chemin: str):
        r = await self.c.get(chemin)
        if r.status_code != 200:
            self.erreurs.append(f"{chemin} : HTTP {r.status_code}")
            return None
        (self.dossier / f"{cle(chemin)}.json").write_bytes(r.content)
        self.ecrits += 1
        return r.json()


async def exporter(sortie: Path) -> dict:
    import httpx

    from src.app import app
    from src.database import init_db

    await init_db()
    if sortie.exists():
        shutil.rmtree(sortie / "api", ignore_errors=True)
    (sortie / "api").mkdir(parents=True, exist_ok=True)

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://ed",
                                 timeout=600) as client:
        ex = Export(client, sortie / "api")
        res = {p: await ex.get(p) for p in FIXES}

        for e in res["/enjeux"] or []:
            await ex.get(f"/enjeux/{e['slug']}")
            for juge in ("retenu", "faible"):
                await ex.get(f"/ecarts/faits?juge={juge}&enjeu={quote(e['slug'], safe='')}&limit=50&offset=0")
            await ex.get(f"/votes/enjeu/{quote(e['slug'], safe='')}")

        for f in (res["/figures"] or {}).get("items", []):
            await ex.get(f"/figures/{f['id']}?limit=1&offset=0")
            await ex.get(f"/figures/{f['id']}/positions")
            await ex.get(f"/figures/{f['id']}/couverture")
            await ex.get(f"/votes/figure/{f['id']}")

        for juge in STATUTS:
            for t in TYPES:
                offset = 0
                while True:
                    q = f"juge={juge}&limit={PAGE_ECARTS}&offset={offset}" + (f"&type={t}" if t else "")
                    d = await ex.get(f"/ecarts/faits?{q}")
                    offset += PAGE_ECARTS
                    if not d or offset >= (d.get("total") or 0):
                        break

        for pas in PAS:
            for vue in VUES:
                for rt in ("true", "false"):
                    for parti in PARTIS:
                        await ex.get(f"/themes/serie?pas={pas}&vue={vue}&retweets={rt}"
                                     + (f"&parti={parti}" if parti else ""))

        semaines = set((res["/themes/sujets"] or {}).get("semaines") or []) | set(
            (res["/revue"] or {}).get("semaines") or [])
        sujets_vus: set = set()
        for s in [None, *sorted(semaines)]:
            d = res["/themes/sujets"] if s is None else await ex.get(f"/themes/sujets?semaine={s}")
            if s is not None:
                await ex.get(f"/revue?semaine={quote(str(s), safe='')}")
            for sj in (d or {}).get("sujets", []):
                if sj.get("id") not in sujets_vus:
                    sujets_vus.add(sj.get("id"))
                    await ex.get(f"/themes/sujets/{sj['id']}")


    # Les pages, marquées statiques
    for f in STATIC.iterdir():
        if f.is_dir():
            continue
        if f.suffix == ".html":
            html = f.read_text(encoding="utf-8").replace("<html", '<html data-statique="1"', 1)
            (sortie / f.name).write_text(html, encoding="utf-8")
        else:
            shutil.copy2(f, sortie / f.name)
    (sortie / "_headers").write_text("/api/*\n  Cache-Control: no-cache\n", encoding="utf-8")
    return {"fichiers": ex.ecrits, "erreurs": ex.erreurs[:20], "nb_erreurs": len(ex.erreurs)}


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--sortie", type=Path, default=SORTIE)
    a = p.parse_args()
    r = asyncio.run(exporter(a.sortie.resolve()))
    print(json.dumps(r, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
