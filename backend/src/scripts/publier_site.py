"""Publie le site figé d'ED Mediawatch sur Cloudflare Pages (gratuit, sans serveur).

    python -m src.scripts.publier_site --creer     # une fois : projet Pages + espace KV des décisions
    python -m src.scripts.publier_site             # chaque semaine : décisions rapatriées, export, envoi

Ordre d'une publication : (1) ramener les décisions des relecteurs (``rapatrier_decisions``),
pour que la page les montre ; (2) exporter (``exporter_site``) ; (3) envoyer avec wrangler,
depuis ``code/infra/pages`` où vivent la fonction et sa configuration.

**Le site doit être derrière Cloudflare Access avant le premier envoi** : il montre des lectures
automatiques pas encore relues. Le script refuse d'envoyer tant que ``ACCESS_TEAM`` est vide dans
``infra/pages/wrangler.toml`` ; ``--sans-access`` force, à ne pas faire.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

PAGES = Path(__file__).resolve().parents[3] / "infra" / "pages"
CONF = PAGES / "wrangler.toml"
PROJET = "ed-mediawatch"
WRANGLER = ["npx", "--yes", "wrangler@4"]


def wrangler(*args: str) -> str:
    r = subprocess.run([*WRANGLER, *args], cwd=PAGES, capture_output=True, text=True, encoding="utf-8",
                       shell=sys.platform == "win32")
    if r.returncode:
        raise SystemExit(f"wrangler {' '.join(args)} : {(r.stderr or r.stdout)[-600:]}")
    return r.stdout


def conf() -> str:
    return CONF.read_text(encoding="utf-8")


def creer() -> None:
    out = wrangler("pages", "project", "list")
    if PROJET not in out:
        wrangler("pages", "project", "create", PROJET, "--production-branch", "main")
        print(f"projet Pages {PROJET} créé")
    if 'id = "A-CREER"' in conf():
        out = wrangler("kv", "namespace", "create", f"{PROJET}-decisions")
        m = re.search(r'id\s*=\s*"([0-9a-f]{32})"', out) or re.search(r'"id"\s*:\s*"([0-9a-f]{32})"', out)
        if not m:
            raise SystemExit(f"identifiant KV introuvable dans : {out[-400:]}")
        CONF.write_text(conf().replace('id = "A-CREER"', f'id = "{m.group(1)}"'), encoding="utf-8")
        print("espace KV des décisions créé")


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--creer", action="store_true", help="créer le projet Pages et l'espace KV")
    p.add_argument("--sans-access", action="store_true")
    p.add_argument("--sans-export", action="store_true")
    a = p.parse_args()
    if a.creer:
        creer()
        return 0
    if re.search(r'ACCESS_TEAM\s*=\s*""', conf()) and not a.sans_access:
        raise SystemExit("ACCESS_TEAM vide dans infra/pages/wrangler.toml : mettre le site derrière "
                         "Cloudflare Access d'abord (voir infra/MISE-EN-SERVICE.md).")
    if 'id = "A-CREER"' in conf():
        raise SystemExit("lancer d'abord `python -m src.scripts.publier_site --creer`")
    from src.scripts import exporter_site, rapatrier_decisions

    print(json.dumps(rapatrier_decisions.rapatrier(), ensure_ascii=False))
    if not a.sans_export:
        import asyncio
        print(json.dumps(asyncio.run(exporter_site.exporter(exporter_site.SORTIE)), ensure_ascii=False))
    print(wrangler("pages", "deploy", "--project-name", PROJET, "--branch", "main",
                   "--commit-dirty=true")[-400:])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
