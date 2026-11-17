"""Couverture de l'historique X par figure (étape 3 du plan de finalisation, critère : 90 % de mois couverts).

Deux sources locales :
- ``donnees/x-historique/etat.json`` : la recherche par mois (``historique_x``), avec un statut par mois ;
- ``donnees/x-timeline/etat.json`` : les pages de profil (``timeline_ed``), avec la date la plus ancienne atteinte.

Un mois compte comme couvert si la recherche l'a fini (« complet » ou « vide confirmé »), ou s'il tombe après la
date la plus ancienne atteinte par le profil. « pages vides », « vide » et « tronqué » sont à relire.

    python -m src.scripts.couverture_historique [--depuis 2022-01] [--jusqua 2026-10]
        -> documents/<date>_couverture-historique.md
"""

from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path

from src.scripts.historique_x import comptes_du_pool

ETUDE = Path(__file__).resolve().parents[4]
RECHERCHE = ETUDE / "donnees" / "x-historique" / "etat.json"
PROFIL = ETUDE / "donnees" / "x-timeline" / "etat.json"
FINIS = {"complet", "vide confirmé"}
CIBLE = 0.9


def mois_entre(depuis: str, jusqua: str) -> list[str]:
    y, m = map(int, depuis.split("-"))
    out = []
    while f"{y:04d}-{m:02d}" <= jusqua:
        out.append(f"{y:04d}-{m:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def lire(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def couverture(compte: str, mois: list[str], recherche: dict, profil: dict) -> dict:
    r = next((v for k, v in recherche.items() if k.lower() == compte.lower()), {})
    p = next((v for k, v in profil.items() if k.lower() == compte.lower()), {})
    depuis_profil = str(p.get("plus_ancien") or "")[:7] if p.get("fin") in ("borne", "fin du profil") else ""
    couverts, a_relire = [], []
    for m in mois:
        statut = (r.get(m) or {}).get("fin")
        if statut in FINIS or (depuis_profil and m >= depuis_profil):
            couverts.append(m)
        else:
            a_relire.append(m)
    return {"compte": compte, "part": len(couverts) / len(mois) if mois else 0, "a_relire": a_relire,
            "recherche": sum(1 for v in r.values() if v.get("fin") in FINIS),
            "profil": f"{p.get('n', 0)} tweets jusqu'au {depuis_profil}" if depuis_profil else
            (f"en cours ({p.get('n', 0)} tweets)" if p else "pas encore lu")}


def plages(mois: list[str]) -> str:
    """« 2022-01 à 2022-06, 2023-03 » : les mois à relire, regroupés."""
    if not mois:
        return ""
    out, debut, prec = [], mois[0], mois[0]
    for m in mois[1:] + [None]:
        suivant = None
        if prec:
            y, mm = map(int, prec.split("-"))
            suivant = f"{y + (mm == 12):04d}-{1 if mm == 12 else mm + 1:02d}"
        if m != suivant:
            out.append(debut if debut == prec else f"{debut} à {prec}")
            debut = m
        prec = m
    return ", ".join(out)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--depuis", default="2022-01")
    p.add_argument("--jusqua", default=f"{date.today():%Y-%m}")
    a = p.parse_args()
    mois = mois_entre(a.depuis, a.jusqua)
    recherche, profil = lire(RECHERCHE), lire(PROFIL)
    lignes_c = [couverture(c, mois, recherche, profil) for c in comptes_du_pool()]
    atteints = sum(1 for x in lignes_c if x["part"] >= CIBLE)
    out = ETUDE / "documents" / f"{date.today():%Y-%m-%d}_couverture-historique.md"
    texte = [f"# Couverture de l'historique X, {a.depuis} à {a.jusqua}", "",
             f"{atteints} figures sur {len(lignes_c)} atteignent {CIBLE:.0%} de mois couverts (critère 1 du plan).", "",
             "| Figure | Couvert | Mois finis par la recherche | Pages de profil | À relire |", "|---|---|---|---|---|"]
    for x in sorted(lignes_c, key=lambda x: x["part"]):
        texte.append(f"| {x['compte']} | {x['part']:.0%} | {x['recherche']} | {x['profil']} | {plages(x['a_relire'])} |")
    out.write_text("\n".join(texte) + "\n", encoding="utf-8")
    print(out, f"{atteints}/{len(lignes_c)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
