"""Convertit un `cookies.txt` (format Netscape, export navigateur) en la valeur
`SITE_COOKIES` attendue par l'extracteur (JSON {domaine: "n=v; n2=v2"}).

Usage :
    python -m src.scripts.cookies_to_site_cookies [chemin_cookies.txt] [sortie.json]

Par défaut : lit `cookies.txt` à la racine du repo, écrit `site_cookies.json`
(gitignoré). **N'affiche jamais les valeurs** de cookies — seulement le nombre
par domaine. Le fichier de sortie est SECRET : à coller dans la variable Railway
`SITE_COOKIES` du backend, jamais committé.

Sécurité : on ne garde que les domaines presse ciblés (paywalls durs souscrits),
pas tout le pot de cookies du navigateur.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# Domaines presse pour lesquels un cookie d'abonné débloque le texte intégral.
# La clé écrite = le domaine de base (l'extracteur fait un `domaine in host`).
TARGET_DOMAINS = [
    "lemonde.fr",
    "lefigaro.fr",
    "mediapart.fr",
    "liberation.fr",
    "lepoint.fr",
    "lexpress.fr",
    "nouvelobs.com",
    "marianne.net",
    "lesechos.fr",
    "latribune.fr",
    "letelegramme.fr",
    "ouest-france.fr",
    "sudouest.fr",
    "ladepeche.fr",
    "lavoixdunord.fr",
]

REPO_ROOT = Path(__file__).resolve().parents[3]


def _parse_netscape(path: Path) -> list[tuple[str, str, str]]:
    """Retourne [(domaine, nom, valeur)] depuis un cookies.txt Netscape."""
    rows: list[tuple[str, str, str]] = []
    for raw in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw.strip()
        # `#HttpOnly_` préfixe une vraie ligne de cookie ; les autres `#` = commentaires.
        if line.startswith("#HttpOnly_"):
            line = line[len("#HttpOnly_"):]
        elif not line or line.startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) < 7:
            continue
        domain, name, value = parts[0], parts[5], parts[6]
        rows.append((domain.lstrip("."), name, value))
    return rows


def build_site_cookies(path: Path) -> dict[str, str]:
    rows = _parse_netscape(path)
    out: dict[str, list[str]] = {d: [] for d in TARGET_DOMAINS}
    seen: dict[str, set[str]] = {d: set() for d in TARGET_DOMAINS}
    for host, name, value in rows:
        for base in TARGET_DOMAINS:
            if host == base or host.endswith("." + base):
                if name not in seen[base]:  # dédoublonne par nom (garde le 1er)
                    out[base].append(f"{name}={value}")
                    seen[base].add(name)
                break
    # Ne garde que les domaines réellement pourvus.
    return {d: "; ".join(pairs) for d, pairs in out.items() if pairs}


def main() -> None:
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else REPO_ROOT / "cookies.txt"
    dst = Path(sys.argv[2]) if len(sys.argv) > 2 else REPO_ROOT / "site_cookies.json"
    if not src.exists():
        print(f"introuvable : {src}")
        sys.exit(1)

    site_cookies = build_site_cookies(src)
    dst.write_text(json.dumps(site_cookies, ensure_ascii=False), encoding="utf-8")

    print(f"source : {src}")
    print(f"sortie : {dst}  (SECRET — gitignoré, à coller dans SITE_COOKIES)")
    if not site_cookies:
        print("aucun cookie trouvé pour les domaines ciblés.")
        return
    print("domaines couverts (nb de cookies) :")
    for d, val in site_cookies.items():
        print(f"  - {d}: {val.count('=')} cookies")


if __name__ == "__main__":
    main()
