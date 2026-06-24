"""Classification thématique déterministe (CAP) sur des énoncés ED typiques."""

import pytest

from src.services.classification.theme_classifier import ThemeClassifier


@pytest.fixture(scope="module")
def clf():
    return ThemeClassifier()


def test_immigration_expulsions(clf):
    r = clf.classify("Il faut expulser tous les clandestins sous OQTF")
    assert r["theme"] == "immigration"
    assert r["subtheme"] == "expulsions"


def test_immigration_cout(clf):
    r = clf.classify("Le coût de l'immigration et l'AME plombent nos finances")
    assert r["theme"] == "immigration"
    assert r["subtheme"] == "cout_immigration"


def test_securite(clf):
    r = clf.classify("L'insécurité explose, il faut plus de places de prison")
    assert r["theme"] == "justice_securite"
    assert r["subtheme"] == "prison"


def test_macro_carburant(clf):
    r = clf.classify("Baisser la TVA sur les carburants pour le pouvoir d'achat")
    assert r["theme"] == "macroeconomie"
    assert r["subtheme"] == "fiscalite_carburant"


def test_macro_retraites(clf):
    r = clf.classify("La réforme des retraites à 64 ans est une injustice")
    assert r["theme"] == "macroeconomie"
    assert r["subtheme"] == "retraites"


def test_energie_nucleaire(clf):
    r = clf.classify("Sortir du nucléaire serait une folie, vive l'EPR")
    assert r["theme"] == "energie"
    assert r["subtheme"] == "mix_energetique"


def test_ue(clf):
    r = clf.classify("L'Union européenne et Bruxelles nous imposent tout, Frexit !")
    assert r["theme"] == "international_ue"
    assert r["subtheme"] == "ue"


def test_ukraine(clf):
    r = clf.classify("Arrêtons d'envoyer des armes en Ukraine contre Poutine")
    assert r["theme"] == "international_ue"
    assert r["subtheme"] == "ukraine"


def test_droits_civiques_woke(clf):
    r = clf.classify("Le wokisme et l'écriture inclusive menacent la République")
    assert r["theme"] == "droits_civiques"


def test_accents_insensitive(clf):
    # Sans accents (typique des tweets) → même résultat.
    r = clf.classify("le cout de l'immigration et les expulsions d'etrangers")
    assert r["theme"] == "immigration"


def test_irrelevant_is_none(clf):
    r = clf.classify("Bonne journée à toutes et à tous, beau temps aujourd'hui")
    assert r["theme"] is None
    assert r["subtheme"] is None


def test_word_boundary_no_false_positive(clf):
    # "internationale" ne doit pas matcher "international" (frontière de mot).
    r = clf.classify("la chanson de l'Internationale a été chantée")
    assert r["theme"] != "international_ue" or r["score"] == 0
