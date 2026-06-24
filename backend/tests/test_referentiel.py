"""Le référentiel JSON est aligné sur le backbone CAP (cadre §2) et préserve
tous les référents chiffrés (analyse en pause)."""

import json

from src.config import BACKEND_DIR
from src.utils import slugify

REF = json.loads((BACKEND_DIR / "data" / "referentiel.json").read_text(encoding="utf-8"))

# Codes CAP officiels : numérotation non consécutive (pas de 11 ni 22).
CAP_CODES = {1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 23}


def _all_referents():
    return [r for t in REF["themes"] for st in t["subthemes"] for r in st["referents"]]


def test_21_cap_major_topics():
    codes = {t["code"] for t in REF["themes"]}
    assert codes == CAP_CODES
    assert len(REF["themes"]) == 21


def test_no_gaps_codes_11_22_absent():
    codes = {t["code"] for t in REF["themes"]}
    assert 11 not in codes and 22 not in codes


def test_every_theme_has_salience():
    valid = {"basse", "moyenne", "haute", "tres_haute"}
    for t in REF["themes"]:
        assert t.get("salience") in valid, t["id"]


def test_referents_preserved_count_and_unique():
    refs = _all_referents()
    keys = [r["key"] for r in refs]
    assert len(refs) == 28  # tous les référents historiques conservés
    assert len(keys) == len(set(keys))  # clés uniques


def test_theme_ids_unique():
    ids = [t["id"] for t in REF["themes"]]
    assert len(ids) == len(set(ids))


def test_slugify():
    assert slugify("Coût de l'immigration !") == "cout-de-l-immigration"
    assert slugify("  Énergie / Nucléaire  ") == "energie-nucleaire"
    assert slugify("") == "x"
