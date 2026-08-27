"""Les colonnes ajoutées par auto-migration arrivent à NULL sur l'existant.

`_autoadd_missing_columns` ajoute les nouvelles colonnes en NULLable sans
réécrire les lignes déjà en base (cf. database.py). Un schéma de réponse qui
exige la valeur casse alors en production — et seulement là, puisqu'une base
de test neuve n'a aucune ligne antérieure.

Vécu le 27/08/2026 : `detection_method` ajouté comme champ requis → HTTP 500 sur
/contradictions en production, 169 tests verts en local. Ce test encode la règle :
tout champ correspondant à une colonne récente doit tolérer NULL.
"""

from datetime import datetime, timezone

import pytest

from src.schemas import ContradictionOut

_CLAIM = {
    "id": 1, "platform": "x", "verbatim": "propos", "canonical": None,
    "claim_type": "normatif", "qty_value": None, "qty_unit": None,
    "speaker_name": "A", "party": "RN", "published_at": None, "confidence": 0.7,
}


def _payload(**over):
    base = {
        "id": 1, "type": 1, "score": 0.9, "status": "pending",
        "rationale": None, "referent_key": None, "validator": None,
        "detected_at": datetime.now(timezone.utc),
        "detection_method": "llm_judge", "judge_version": "judge-v1",
        "claim_a": dict(_CLAIM), "claim_b": dict(_CLAIM, id=2),
    }
    base.update(over)
    return base


def test_legacy_row_without_provenance_still_serializes():
    """Arête créée avant le suivi de provenance : colonne à NULL."""
    out = ContradictionOut.model_validate(_payload(detection_method=None, judge_version=None))
    # Ces arêtes sont déterministes par construction : le juge n'existait pas.
    assert out.detection_method == "deterministe"
    assert out.judge_version is None


def test_provenance_is_preserved_when_present():
    out = ContradictionOut.model_validate(_payload())
    assert out.detection_method == "llm_judge"
    assert out.judge_version == "judge-v1"


@pytest.mark.parametrize("missing", ["detection_method", "judge_version"])
def test_absent_key_does_not_raise(missing):
    """Champ carrément absent du dict (ORM sans l'attribut) : pas d'erreur."""
    payload = _payload()
    payload.pop(missing)
    ContradictionOut.model_validate(payload)
