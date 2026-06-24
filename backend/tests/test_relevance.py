"""Régression du détecteur prise_de_parole / mention (la « confusion de fond »).

Cas piégeux tirés des invariants documentés dans relevance.py : nom complet
d'abord, frontière de mot, noms ambigus jamais matchés seuls, direction du verbe.
On teste contre le **vrai** lexique (data/rn_keywords.json) avec des phrases
fabriquées — donc le comportement réellement déployé.
"""

import pytest

from src.services.collection.relevance import build_index
from src.vocabulary import Nature


@pytest.fixture(scope="module")
def index():
    # Quelques figures réelles + une figure à patronyme ambigu (collision « Martin »).
    return build_index(["Jordan Bardella", "Marine Le Pen", "Paul Martin"])


# --- Pertinence (concerne le RN / une figure ?) -----------------------------

def test_party_is_relevant(index):
    assert index.assess("Le RN présente son programme")["relevant"] is True


def test_full_name_is_relevant(index):
    assert index.assess("Jordan Bardella tient un meeting")["relevant"] is True


def test_unrelated_is_not_relevant(index):
    v = index.assess("La météo sera belle sur la Bretagne ce week-end")
    assert v["relevant"] is False
    assert v["nature"] is None


def test_word_boundary_france_not_ranc(index):
    # « France » ne doit pas déclencher un patronyme par sous-chaîne.
    assert index.assess("La France a tranché lors du scrutin")["relevant"] is False


def test_ambiguous_surname_not_matched_alone(index):
    # « Martin » (patronyme ambigu) ne matche jamais seul, même si « Paul Martin »
    # est dans le pool.
    assert index.assess("Le martin-pêcheur niche au bord de l'eau")["relevant"] is False


# --- Nature : prise de parole vs mention ------------------------------------

def test_attribution_selon_is_prise_de_parole(index):
    v = index.assess("Selon Marine Le Pen, l'immigration coûte trop cher")
    assert v["nature"] == Nature.PRISE_DE_PAROLE
    assert v["is_statement"] is True


def test_subject_directional_verb_is_prise_de_parole(index):
    # Figure en position sujet juste avant un verbe directionnel.
    v = index.assess("Le RN dénonce la politique migratoire du gouvernement")
    assert v["nature"] == Nature.PRISE_DE_PAROLE


def test_passive_directional_verb_is_mention(index):
    # Même verbe, mais le RN est l'OBJET (passif) → simple mention.
    v = index.assess("Le RN est dénoncé par l'ensemble de la majorité")
    assert v["nature"] == Nature.MENTION
    assert v["is_statement"] is False


def test_strong_verb_near_figure_is_prise_de_parole(index):
    v = index.assess("Bardella propose une loi sur l'immigration")
    assert v["nature"] == Nature.PRISE_DE_PAROLE


def test_interview_marker_is_prise_de_parole(index):
    v = index.assess("Marine Le Pen, dans un entretien, explique sa position")
    assert v["nature"] == Nature.PRISE_DE_PAROLE


def test_mere_coverage_is_mention(index):
    # Le parti est nommé/couvert, sans parole directe attribuée.
    v = index.assess("Le RN progresse dans les sondages selon une étude récente")
    assert v["nature"] == Nature.MENTION


# --- Attribution des métadonnées --------------------------------------------

def test_personalities_use_display_name(index):
    v = index.assess("Selon Marine Le Pen, il faut agir")
    assert any("Le Pen" in p or "le pen" in p.lower() for p in v["personalities"])


def test_keywords_uppercase_sigle(index):
    v = index.assess("Le RN dénonce cette mesure")
    assert "RN" in v["keywords"]
