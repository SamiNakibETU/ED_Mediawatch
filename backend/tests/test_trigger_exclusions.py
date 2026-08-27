"""Exclusions contextuelles des déclencheurs quantitatifs.

Cas réel (corpus du 26/08/2026) : « un déficit pluviométrique de plus de 70 % »
était rattaché au référent `deficit_public::pct_pib`, héritait de l'unité
« % du PIB », et devenait donc comparable à « ramener le déficit public à 5 % du
PIB » — produisant une contradiction entre la pluie et le budget de l'État.

Un rattachement erroné n'est pas une donnée mal rangée : c'est le point de départ
d'une contradiction indéfendable. Mieux vaut rater une quantité.
"""

from src.services.analysis.claim_extractor import _load_triggers, extract_from_text


def _keys(text: str) -> list[str]:
    return [r["referent_key"] for r in extract_from_text(text, _load_triggers())]


def test_meteorological_deficit_not_linked_to_public_deficit():
    assert _keys("Avec un déficit pluviométrique de plus de 70 % en moyenne.") == []


def test_precipitation_wording_also_excluded():
    assert _keys("Un déficit de précipitations proche de 70 % cette année.") == []


def test_budget_deficit_still_linked():
    keys = _keys("Il faut ramener le déficit public à 5 % du PIB en 2027.")
    assert "economie::deficit_public::pct_pib" in keys


def test_exclusion_is_sentence_scoped():
    # L'exclusion vaut pour la phrase où elle apparaît, pas pour tout l'article :
    # une phrase budgétaire propre reste rattachée.
    text = (
        "Le déficit pluviométrique atteint 70 %. "
        "Par ailleurs, le déficit public doit revenir à 3 % du PIB."
    )
    keys = _keys(text)
    assert keys.count("economie::deficit_public::pct_pib") == 1
