"""Précision des nombres nus — supprime les faux positifs observés en prod.

Cas réels qui créaient de fausses contradictions « expulsions/an » et
« recrutements » (l'extracteur raflait un nombre portant une autre unité).
"""

from src.services.analysis.quantity import find_plain_numbers, find_quantities

NB = "nb"


def _values(text: str) -> list[float]:
    typed = find_quantities(text)
    plains = find_plain_numbers(text, exclude_spans=[(q.start, q.end) for q in typed])
    return [q.value for q in plains]


def test_euros_not_a_plain_count():
    # « 6000 euros » ne doit pas devenir « 6000 expulsions ».
    assert 6000.0 not in _values("condamnée à verser 6000 euros à un Algérien sous OQTF")


def test_days_not_a_plain_count():
    # « 210 jours » de rétention ≠ 210 expulsions.
    assert 210.0 not in _values("allonge leur maintien en CRA jusqu'à 210 jours")


def test_amendments_not_a_plain_count():
    assert 400.0 not in _values("déposé pas moins de 400 sous-amendements")


def test_injured_not_a_plain_count():
    assert 178.0 not in _values("178 policiers et gendarmes blessés")


def test_real_count_kept():
    # Un vrai compte (« 35000 expulsions ») doit rester capté.
    assert 35000.0 in _values("le RN promet 35000 expulsions par an")


def test_percentage_excluded_from_plain():
    # « 47 % » est une quantité typée (PCT), pas un nombre nu.
    assert 47.0 not in _values("une hausse de 47% des passages aux urgences")
