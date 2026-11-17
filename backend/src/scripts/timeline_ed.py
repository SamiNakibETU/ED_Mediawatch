"""Historique X des figures du pool par les pages de profil de xitter.cf, pour ED Mediawatch.

Pourquoi : depuis fin octobre 2026, la recherche de xitter.cf pose un défi anti-robot (HTTP 403), qui arrête
``historique_x``. Les pages de profil restent ouvertes et leur robots.txt les autorise. Le lecteur existe déjà dans
X-tools (``canaux/timeline_x.py``, skill ``collecte-x``) : ce script le réutilise tel quel et change seulement le
dossier de sortie, pour que les données restent dans l'étude qui les demande (``donnees/x-timeline/``).

Ordre : les comptes du pool jamais collectés d'abord, puis ceux de l'historique par recherche, pour boucher leurs
mois vides. Une requête à la fois, pauses de 4 s, arrêt devant un défi ; relancer reprend au dernier curseur.
Limite connue : X borne la profondeur d'un profil ; un compte très actif peut s'arrêter sur « fin du profil »
avant la borne. Le statut de chaque compte le dit dans ``etat.json``.

Usage :  python -m src.scripts.timeline_ed [--borne 2022-01-01] [--comptes a b c]
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

from src.scripts.historique_x import comptes_du_pool

LECTEUR = Path(r"D:\Sami\iris\etudes\X-desinformation\X-tools\canaux\timeline_x.py")
ETUDE = Path(__file__).resolve().parents[4]
SORTIE = ETUDE / "donnees" / "x-timeline"
HISTORIQUE = ETUDE / "donnees" / "x-historique" / "etat.json"


def charger_lecteur():
    spec = importlib.util.spec_from_file_location("timeline_x", LECTEUR)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.DOSSIER = SORTIE            # les données d'ED restent dans ED
    return mod


def ordre() -> list[str]:
    """Les comptes jamais collectés d'abord, puis ceux de l'historique par recherche."""
    faits = set()
    if HISTORIQUE.exists():
        faits = {h.lower() for h in json.loads(HISTORIQUE.read_text(encoding="utf-8"))}
    pool = comptes_du_pool()
    return [c for c in pool if c.lower() not in faits] + [c for c in pool if c.lower() in faits]


def main() -> int:
    mod = charger_lecteur()
    if "--comptes" not in sys.argv:
        sys.argv += ["--comptes", *ordre()]
    if "--borne" not in sys.argv:
        sys.argv += ["--borne", "2022-01-01"]
    return mod.main()


if __name__ == "__main__":
    raise SystemExit(main())
