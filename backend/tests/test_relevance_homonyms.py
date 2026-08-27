"""Faux positifs d'attribution : patronymes collidant avec des noms communs.

Cas observés sur une collecte réelle (85 articles, 26/08/2026) : « parc Dragon
Ball » attribué à Nicolas Dragon, « cinéma bourgeois » à Robert Le Bourgeois,
« Renaud Girard » à Christian Girard. Une mauvaise attribution n'est pas un
détail de tri : le L0 paierait pour extraire des déclarations imputées à la
mauvaise personne, et une contradiction bâtie dessus serait indéfendable.

Trois gardes cumulatives, toutes sur le texte d'origine (la normalisation
détruit accents et casse) : capitalisation, prénom d'homonyme, nom composé.
"""

import pytest

from src.services.collection.relevance import build_index


@pytest.fixture
def index():
    # Figures dont le patronyme est aussi un nom commun ou porté par un homonyme.
    return build_index([
        "Jordan Bardella",
        "Nicolas Dragon",
        "Robert Le Bourgeois",
        "Christian Girard",
        "Sarah Knafo",
    ])


def test_common_noun_lowercase_not_matched(index):
    # « bourgeois » en minuscule : nom commun, pas la figure.
    v = index.assess("Encore un effort pour critiquer le cinéma bourgeois")
    assert v["personalities"] == []


def test_capitalized_compound_proper_noun_not_matched(index):
    # « Dragon Ball » : nom propre composé étranger à Nicolas Dragon.
    v = index.assess("Un parc Dragon Ball ouvrira près de Paris")
    assert v["personalities"] == []


def test_homonym_with_different_first_name_not_matched(index):
    # « Renaud Girard » (journaliste) n'est pas « Christian Girard ».
    v = index.assess("Renaud Girard : en Europe, marchons-nous vers la guerre ?")
    assert v["personalities"] == []


def test_expected_first_name_still_matches(index):
    v = index.assess("Christian Girard a défendu cette position hier")
    assert v["personalities"] == ["Christian Girard"]


def test_bare_surname_capitalized_still_matches(index):
    # Le cas légitime : patronyme seul, capitalisé, sans homonyme ni composé.
    v = index.assess("Selon Bardella, la loi doit changer")
    assert v["personalities"] == ["Jordan Bardella"]


def test_full_name_always_matches(index):
    v = index.assess("Jordan Bardella propose une loi sur l'immigration")
    assert v["personalities"] == ["Jordan Bardella"]
