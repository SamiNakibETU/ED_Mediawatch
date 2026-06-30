"""L0 — garde-fou anti-hallucination : le verbatim doit exister dans la source."""

from src.services.analysis.declaration_extractor import (
    verbatim_in_source,
    worth_segmenting,
)


def test_worth_segmenting_skips_noise():
    # Coût : on ne segmente pas (donc pas d'appel LLM) le bruit.
    assert not worth_segmenting("")
    assert not worth_segmenting("https://t.co/abc")          # lien seul
    assert not worth_segmenting("👍🔥")                         # emojis seuls
    assert not worth_segmenting("Merci !")                    # trop court


def test_worth_segmenting_keeps_real_content():
    assert worth_segmenting(
        "Il faut rétablir la double peine et expulser les délinquants étrangers."
    )
    # URL présente mais vrai contenu autour → on segmente.
    assert worth_segmenting(
        "Le coût de l'immigration explose, voir https://x.com/abc pour les chiffres."
    )


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
