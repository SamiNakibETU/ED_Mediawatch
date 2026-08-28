"""Un article de presse n'est jamais, en bloc, la parole d'une personne.

Règle absolue de l'observatoire : **sans attribution certaine, on n'attribue
pas**. Un papier qui mentionne une figure contient aussi la voix du journaliste
et de tiers cités. Présumer que la seule figure suivie mentionnée est l'auteur
de tout le contenu fabrique des imputations fausses — et une imputation fausse,
publiée, retourne l'arme contre l'observatoire.

Deux occurrences réelles, sur les DEUX chemins d'extraction :
  * L0 (`declaration_extractor`) — des propos de Marylise Léon et Benjamin
    Haddad prêtés à Marine Le Pen, puis des « revirements » bâtis dessus ;
  * quantitatif (`claim_extractor`) — un chiffre énoncé par Benjamin Haddad
    dans un papier franceinfo crédité à Marine Le Pen.

La correction d'alors — n'attribuer aucun propos de presse — tenait la règle
mais coûtait cher : TOUTE la presse tombait en « non attribué », donc hors de la
comparaison, alors que rattacher un propos à quelqu'un à une date est l'objet
même du produit. La réponse n'est pas de deviner, c'est de faire dire au texte
qui parle, puis de le vérifier. Ces tests verrouillent les deux moitiés :
jamais de déduction, et jamais d'attribution non vérifiée.
"""

import inspect
import re

from src.services.analysis import claim_extractor, declaration_extractor
from src.services.analysis.declaration_extractor import attributed_speaker

SOURCE = (
    "Face aux patrons, Marine Le Pen déroule un programme libéral. "
    "« Il faut baisser les impôts », a déclaré Marine Le Pen devant le MEDEF. "
    "De son côté, Marylise Léon estime que la réforme est injuste. "
    "Jordan Bardella n’a pas réagi."
)
SUIVIS = {"Marine Le Pen": 76, "Éric Ciotti": 12}


# ── La règle : jamais de déduction ───────────────────────────────────────

def test_l0_never_presumes_a_speaker_from_mentions():
    src = inspect.getsource(declaration_extractor.run_declaration_extraction)
    assert not re.search(r"speaker\w*\s*=\s*mp\[0\]", src)
    # L'attribution de presse doit passer par le garde-fou, jamais en direct.
    assert "attributed_speaker(decl.speaker" in src


def test_quantitative_extractor_never_presumes_a_speaker_for_press():
    src = inspect.getsource(claim_extractor)
    press = src[src.index('platform="press"') - 3000 : src.index('platform="press"') + 200] \
        if 'platform="press"' in src else src
    assert not re.search(r"speaker\s*=\s*mp\[0\]", press), (
        "l'extracteur quantitatif présume à nouveau un locuteur depuis les "
        "mentions d'un article — cf. docstring de ce test"
    )


def test_rule_is_documented_where_it_is_enforced():
    """La règle doit rester expliquée dans le code : sans le pourquoi, elle
    sera « simplifiée » par la prochaine personne qui passe."""
    for mod in (declaration_extractor, claim_extractor):
        src = inspect.getsource(mod)
        assert "JAMAIS de locuteur présumé" in src, f"{mod.__name__} a perdu la justification"


# ── Le garde-fou : jamais d'attribution non vérifiée ─────────────────────

def test_named_speaker_present_in_the_text_is_accepted():
    """Le texte dit qui parle : c'est le seul cas où l'on attribue."""
    assert attributed_speaker("Marine Le Pen", SOURCE, SUIVIS) == ("Marine Le Pen", 76)


def test_partial_name_resolves_to_the_followed_figure():
    """« Le Pen » et « Marine Le Pen » doivent être la MÊME voix : sans ce
    rattachement, deux graphies feraient deux locuteurs et il n'y aurait plus
    rien à comparer dans le temps."""
    assert attributed_speaker("Le Pen", SOURCE, SUIVIS) == ("Marine Le Pen", 76)


def test_speaker_outside_the_pool_is_kept_but_unlinked():
    """Une voix qui n'est pas suivie reste une voix. La consigner nommément
    vaut mieux que de la verser au tas « non attribué » : c'est ce qui permet
    de confronter un propos RN à celui d'un syndicaliste."""
    assert attributed_speaker("Marylise Léon", SOURCE, SUIVIS) == ("Marylise Léon", None)


def test_name_absent_from_the_source_is_refused():
    """Le modèle propose, le texte dispose. Un nom qui n'est pas dans le papier
    n'a pas pu y être désigné comme l'auteur du propos."""
    assert attributed_speaker("Éric Ciotti", SOURCE, SUIVIS) == (None, None)
    assert attributed_speaker("Emmanuel Macron", SOURCE, SUIVIS) == (None, None)


def test_a_collective_is_not_a_speaker():
    """« Le gouvernement » n'a pas de position qu'on puisse suivre dans le
    temps : ce n'est pas quelqu'un."""
    for junk in ("le gouvernement", "une source proche", "", None, "   "):
        assert attributed_speaker(junk, SOURCE, SUIVIS) == (None, None)


def test_ambiguous_surname_is_refused():
    """Deux Le Pen dans le même papier : on n'attribue pas. Choisir au hasard
    entre deux figures est exactement le défaut qu'on a corrigé."""
    deux = {"Marine Le Pen": 1, "Jean-Marie Le Pen": 2}
    assert attributed_speaker("Le Pen", SOURCE, deux) == (None, None)


def test_x_posts_keep_their_certain_attribution():
    """Sur X, le compte EST l'auteur : cette attribution-là ne se discute pas,
    et le chemin de presse ne doit pas l'avoir affaiblie."""
    src = inspect.getsource(declaration_extractor.run_declaration_extraction)
    assert "speaker=p.full_name" in src.replace(" ", "").replace("\n", "") \
        or "speaker=p.full_name" in src
