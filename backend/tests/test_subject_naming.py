"""Nommer un sujet, c'est nommer un OBJET DE DÉBAT — pas une personne.

Le sommaire affichait « Jordan Bardella » comme sujet. Un nom propre ne dit pas
de quoi on parle : il rassemble tout ce qui a été dit d'une personne, ce qui
n'est pas un objet de débat mais un dossier. Deux propos sur « la candidature de
Jordan Bardella » se confrontent ; deux propos sur « Jordan Bardella » ne se
confrontent pas, ils coexistent.

Il affichait aussi « davantage deputes designe gagner » : le sac d'entités trié
par ordre alphabétique, échappé du moteur jusqu'à l'écran. Le nommage LLM le
remplace, mais il ne traitait que 40 sujets par passe pour 900 en attente.
"""

import inspect

from src.pipeline.stages import BY_NAME
from src.services.analysis import subject_labeller


def test_a_person_is_not_a_subject():
    """La règle doit être écrite dans la consigne : sans elle, le modèle nomme
    ce qu'il voit le plus souvent, c'est-à-dire le locuteur."""
    sys = subject_labeller._SYSTEM
    assert "NOM DE PERSONNE n'est pas un objet de débat" in sys
    assert "Jordan Bardella" in sys, "l'exemple concret vaut mieux que la règle seule"


def test_incoherent_groups_are_flagged_not_named():
    """Un groupe mal formé signalé vaut mieux qu'un titre inventé : le titre
    masquerait le défaut de regroupement au lieu de le montrer."""
    src = inspect.getsource(subject_labeller.label_subjects)
    assert 'obj.status = "incoherent"' in src
    assert "coherent=false" in subject_labeller._SYSTEM


def test_naming_covers_the_backlog_not_a_sample():
    """40 sujets par passe pour 900 en attente, c'est quatre jours pendant
    lesquels le sommaire affiche des sacs de mots. À 0,0002 $ le sujet, la
    prudence ne protège de rien."""
    src = inspect.getsource(BY_NAME["label_subjects"].run)
    assert "limit=400" in src
    assert "min_speakers=1" in src


def test_declared_targets_feed_the_prompt():
    """Le modèle a déjà nommé l'objet propos par propos à l'extraction
    (`stance_target`) : le lui redemander depuis les extraits gaspille sa
    lecture et produit des noms qui divergent d'une passe à l'autre."""
    src = inspect.getsource(subject_labeller.label_subjects)
    assert "Claim.stance_target" in src
    assert "Objets déclarés à l'extraction" in src
