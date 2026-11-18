"""Publie le site figé d'ED Mediawatch sur Cloudflare Pages (gratuit, sans serveur).

    python -m src.scripts.publier_site --creer     # une fois : projet Pages + espace KV des décisions
    python -m src.scripts.publier_site             # chaque semaine : décisions rapatriées, export, envoi

Ordre d'une publication : (1) ramener les décisions des relecteurs (``rapatrier_decisions``),
pour que la page les montre ; (2) exporter (``exporter_site``) ; (3) envoyer avec wrangler,
depuis ``code/infra/pages`` où vivent la fonction et sa configuration.

**Le site doit être fermé avant le premier envoi** : il montre des lectures automatiques pas
encore relues. Deux portes possibles : un compte par relecteur (``--relecteur NOM``, mot de passe
vérifié par ``functions/_middleware.js``), ou Cloudflare Access (``ACCESS_TEAM`` dans
``wrangler.toml``). Sans l'une ni l'autre, le script refuse d'envoyer ; ``--sans-access`` force,
à ne pas faire.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

PAGES = Path(__file__).resolve().parents[3] / "infra" / "pages"
# Comptes des relecteurs : hors du dépôt git (code/), dans admin/ de l'étude.
ADMIN = Path(__file__).resolve().parents[4] / "admin"
COMPTES = ADMIN / "relecteurs.json"            # nom -> empreinte SHA-256 (ce qui part chez Cloudflare)
MOTS = ADMIN / "acces-relecteurs.txt"          # nom et mot de passe, à transmettre à chaque relecteur
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


def relecteur(nom: str) -> None:
    """Crée (ou renouvelle) le compte d'un relecteur et met à jour le secret RELECTEURS du projet."""
    import hashlib
    import secrets
    from datetime import date

    if not re.fullmatch(r"[a-z0-9-]{2,30}", nom):
        raise SystemExit("nom de relecteur : minuscules, chiffres, tirets (ex. sami, relecteur-1)")
    ADMIN.mkdir(parents=True, exist_ok=True)
    comptes = json.loads(COMPTES.read_text(encoding="utf-8")) if COMPTES.exists() else {}
    mot = secrets.token_urlsafe(12)
    comptes[nom] = hashlib.sha256(mot.encode()).hexdigest()
    r = subprocess.run([*WRANGLER, "pages", "secret", "put", "RELECTEURS", "--project-name", PROJET],
                       cwd=PAGES, input=json.dumps(comptes), capture_output=True, text=True,
                       encoding="utf-8", shell=sys.platform == "win32")
    if r.returncode:
        raise SystemExit(f"secret non posé : {(r.stderr or r.stdout)[-400:]}")
    COMPTES.write_text(json.dumps(comptes, indent=1), encoding="utf-8")
    with MOTS.open("a", encoding="utf-8") as f:
        f.write(f"{date.today():%Y-%m-%d}  {nom}  {mot}\n")
    print(f"compte {nom} posé ; identifiants dans {MOTS}")


def envoyer(morceau_mo: float) -> str:
    """Envoie le site. Par morceaux : un VPN sur le poste coupe les gros envois (18/11/2026, « other side
    closed » sur un envoi de 17 Mo). Cloudflare garde les fichiers déjà reçus (empreinte de contenu) :
    chaque déploiement intermédiaire n'envoie que le nouveau morceau, le dernier ne renvoie rien."""
    import shutil
    import tempfile

    from src.scripts.exporter_site import SORTIE

    deployer = lambda d: wrangler("pages", "deploy", str(d), "--project-name", PROJET, "--branch", "main",
                                  "--commit-dirty=true")
    if morceau_mo <= 0:
        return deployer(SORTIE)
    pages = [f for f in SORTIE.iterdir() if f.is_file()]
    api = sorted((SORTIE / "api").iterdir(), key=lambda f: f.name)
    lots, lot, poids = [], [], 0
    for f in api:
        lot.append(f)
        poids += f.stat().st_size
        if poids >= morceau_mo * 1e6:
            lots.append(lot)
            lot, poids = [], 0
    if lot:
        lots.append(lot)
    deja: list[Path] = []
    for i, lot in enumerate(lots[:-1], 1):
        deja += lot
        d = Path(tempfile.mkdtemp(prefix=f"ed-site-{i}-"))
        (d / "api").mkdir()
        for f in pages:
            shutil.copy2(f, d / f.name)
        for f in deja:
            shutil.copy2(f, d / "api" / f.name)
        for essai in range(3):
            try:
                deployer(d)
                break
            except SystemExit:
                if essai == 2:
                    raise
        print(f"morceau {i}/{len(lots)} envoyé", flush=True)
    return deployer(SORTIE)


def protege() -> bool:
    """Le site a-t-il une porte ? Un compte relecteur au moins, ou Cloudflare Access."""
    comptes = json.loads(COMPTES.read_text(encoding="utf-8")) if COMPTES.exists() else {}
    return bool(comptes) or not re.search(r'ACCESS_TEAM\s*=\s*""', conf())


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--creer", action="store_true", help="créer le projet Pages et l'espace KV")
    p.add_argument("--relecteur", metavar="NOM", help="créer ou renouveler le compte d'un relecteur")
    p.add_argument("--sans-access", action="store_true")
    p.add_argument("--sans-export", action="store_true")
    p.add_argument("--morceau-mo", type=float, default=4.0,
                   help="taille des envois successifs (Mo) ; 0 = tout d'un coup")
    a = p.parse_args()
    if a.creer:
        creer()
        return 0
    if a.relecteur:
        relecteur(a.relecteur)
        return 0
    if not protege() and not a.sans_access:
        raise SystemExit("aucun compte relecteur ni Cloudflare Access : `--relecteur sami` d'abord "
                         "(voir infra/pages/README.md).")
    if 'id = "A-CREER"' in conf():
        raise SystemExit("lancer d'abord `python -m src.scripts.publier_site --creer`")
    from src.scripts import exporter_site, rapatrier_decisions

    print(json.dumps(rapatrier_decisions.rapatrier(), ensure_ascii=False))
    if not a.sans_export:
        import asyncio
        print(json.dumps(asyncio.run(exporter_site.exporter(exporter_site.SORTIE)), ensure_ascii=False))
    print(envoyer(a.morceau_mo)[-400:])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
