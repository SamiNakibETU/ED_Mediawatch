"""Un article de presse n'est jamais, en soi, la parole d'une personne.

Relevé en production le 04/09/2026 : les six déclarations en tête de la une
venaient toutes de la presse et s'affichaient toutes entre guillemets sous le
nom du locuteur. Quatre étaient des phrases de journaliste — « Marine Le Pen
assure avoir elle-même souhaité ce départ », à la troisième personne, ou
« répétée ce samedi par Jordan Bardella depuis la Foire de Châlons », qui n'est
même pas une phrase.

Le garde-fou d'extraction vérifiait que le verbatim était bien dans l'article :
fidélité au DOCUMENT. La page la lisait comme la fidélité au LOCUTEUR. Ces
tests gèlent la séparation des deux.
"""

from src.routers.declarations import _empreinte
from src.services.analysis.quotation import DIRECT, RAPPORTE, style_de_citation

ARTICLE = (
    "Interrogé samedi à la Foire de Châlons, le député RN a été catégorique. "
    "« Nous sanctionnerons le port du voile dans l'espace public », a déclaré "
    "Jean-Philippe Tanguy. Marine Le Pen assure avoir elle-même souhaité ce "
    "départ. La promesse d'un référendum sur l'immigration, répétée ce samedi "
    "par Jordan Bardella, figure au programme."
)


def test_words_inside_the_quotation_marks_are_the_speakers():
    assert style_de_citation(
        "Nous sanctionnerons le port du voile dans l'espace public", ARTICLE) == DIRECT


def test_a_journalists_sentence_about_someone_is_not_a_quotation():
    """Le cas qui a été publié : une phrase à la troisième personne, exacte dans
    le document, et fausse dès qu'on l'entoure de guillemets sous un nom."""
    assert style_de_citation(
        "Marine Le Pen assure avoir elle-même souhaité ce départ.", ARTICLE) == RAPPORTE


def test_a_fragment_of_narration_is_not_a_quotation():
    assert style_de_citation(
        "répétée ce samedi par Jordan Bardella", ARTICLE) == RAPPORTE


def test_a_quotation_swallowed_with_its_attribution_tail_is_reported():
    """« … » a déclaré X : pris ensemble, ce n'est plus ce que X a dit, c'est ce
    que le journal écrit. Un guillemet ouvrant en tête ne suffit pas."""
    assert style_de_citation(
        "« Nous sanctionnerons le port du voile dans l'espace public », a déclaré "
        "Jean-Philippe Tanguy", ARTICLE) == RAPPORTE


def test_the_quotation_survives_normalisation():
    """Accents, apostrophes courbes et espaces insécables varient entre le
    rendu du modèle et le document ; la localisation ne doit pas s'y casser."""
    assert style_de_citation(
        "Nous sanctionnerons le port du voile dans l’espace public", ARTICLE) == DIRECT


def test_a_verbatim_absent_from_the_document_is_never_promoted():
    """Introuvable : on ne sait pas, donc on ne prétend pas citer. L'inconnu
    n'est pas du style direct — même règle que partout ailleurs."""
    assert style_de_citation("une phrase qui n'y est pas du tout", ARTICLE) == RAPPORTE
    assert style_de_citation("", ARTICLE) == RAPPORTE
    assert style_de_citation("Nous sanctionnerons", "") == RAPPORTE


def test_an_opening_quote_alone_does_not_make_a_quotation():
    """Une citation qui commence ne couvre pas forcément le passage retenu."""
    source = "« Je le dis clairement, dit-il, et le journal ajoute autre chose."
    assert style_de_citation("et le journal ajoute autre chose", source) == RAPPORTE


# ── Ce que la une en fait ──────────────────────────────────────────────────

def test_the_same_sentence_carried_by_two_outlets_appears_once():
    """Deux journaux qui citent la même phrase produisent deux déclarations,
    dans deux articles : le dédoublonnage par source les laissait toutes les
    deux en tête de la une. Qu'une phrase soit reprise ailleurs pèse déjà dans
    le score par la reprise presse ; ce n'est pas une raison de l'afficher deux
    fois."""
    a = "Je soumettrai aux Français par référendum une grande loi de lutte"
    b = '"Je soumettrai aux Français, par référendum, une grande loi de lutte"'
    assert _empreinte(a) == _empreinte(b)


def test_two_different_statements_keep_their_own_place():
    assert _empreinte("Nous sanctionnerons le port du voile") != _empreinte(
        "Nous supprimerons l'aide médicale d'État")
