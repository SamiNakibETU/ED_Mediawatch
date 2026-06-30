"""L0 — garde-fou anti-hallucination : le verbatim doit exister dans la source."""

from src.services.analysis.declaration_extractor import verbatim_in_source


SOURCE = (
    "« La France d'abord », a déclaré Jordan Bardella. "
    "Il faut rétablir la double peine et expulser les délinquants étrangers. "
    "Le coût de l'immigration atteint 80 milliards d'euros par an selon lui."
)


def test_exact_substring_accepted():
    assert verbatim_in_source("rétablir la double peine", SOURCE)


def test_typographic_normalization_tolerated():
    # Guillemets droits vs typographiques + accents/casse → toléré.
    assert verbatim_in_source('"la france d\'abord"', SOURCE)


def test_hallucinated_verbatim_rejected():
    # Propos jamais tenu dans la source → rejeté.
    assert not verbatim_in_source("il faut quitter l'euro immédiatement", SOURCE)


def test_altered_number_rejected():
    # Le LLM a changé le chiffre (80 → 90) : ce n'est plus le verbatim → rejeté.
    assert not verbatim_in_source("90 milliards d'euros par an", SOURCE)


def test_too_short_rejected():
    assert not verbatim_in_source("la France", SOURCE)


def test_empty_rejected():
    assert not verbatim_in_source("", SOURCE)
