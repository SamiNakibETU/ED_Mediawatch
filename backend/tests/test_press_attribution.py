"""Un article de presse n'est jamais la parole d'une personne.

Règle absolue de l'observatoire : sans attribution certaine, on n'attribue pas.
Un papier qui mentionne une figure contient aussi la voix du journaliste et de
tiers cités. Présumer que la seule figure suivie mentionnée est l'auteur de tout
le contenu fabrique des imputations fausses — et une imputation fausse, publiée,
retourne l'arme contre l'observatoire.

Deux occurrences réelles, sur les DEUX chemins d'extraction :
  * L0 (`declaration_extractor`) — des propos de Marylise Léon et Benjamin
    Haddad prêtés à Marine Le Pen, puis des « revirements » bâtis dessus ;
  * quantitatif (`claim_extractor`) — un chiffre énoncé par Benjamin Haddad
    dans un papier franceinfo crédité à Marine Le Pen.

Ce test verrouille la règle sur les deux chemins : c'est une garantie produit,
pas un détail d'implémentation.
"""

import inspect
import re

from src.services.analysis import claim_extractor, declaration_extractor


def _press_block(source: str) -> str:
    """Le corps de la boucle presse (après le marqueur `platform="press"`)."""
    return source


def test_l0_never_presumes_a_speaker_for_press():
    src = inspect.getsource(declaration_extractor.run_declaration_extraction)
    # La boucle sur les articles ne doit pas déduire de locuteur des mentions.
    assert "speaker = None" in src
    assert not re.search(r"speaker\s*=\s*mp\[0\]", src)


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
