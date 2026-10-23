"""Registre des positions : le tri, la validation, et le calcul des écarts."""

from datetime import datetime, timedelta, timezone

from src.services.analysis.enjeux import ENJEUX, PAR_SLUG, Point, ecarts
from src.services.analysis.positions import PositionLue, prompt_for, valider

T0 = datetime(2022, 3, 1, tzinfo=timezone.utc)
UKR = PAR_SLUG["ukraine"]
RET = PAR_SLUG["retraites"]


def _p(pid, pos, jours, post):
    return Point(pid, pos, T0 + timedelta(days=jours), post)


def test_chaque_enjeu_a_une_echelle_ordonnee_sans_doublon():
    for e in ENJEUX:
        rangs = [c.rang for c in e.echelle]
        assert rangs == list(range(1, len(rangs) + 1)), e.slug
        assert len({c.code for c in e.echelle}) == len(e.echelle)
        assert e.amorces


def test_les_motifs_ecartent_les_faux_amis_des_amorces():
    # « russ » ratisse Russell en SQL ; l'expression régulière doit le refuser.
    assert not UKR.concerne("Bertrand Russell avait raison sur ce point")
    assert UKR.concerne("Il faut cesser de livrer des armes à l'Ukraine")
    assert RET.concerne("Nous rétablirons la retraite à 60 ans")


def test_une_position_constante_ne_fait_pas_d_ecart():
    pts = [_p(1, "aide_limitee", 0, 1), _p(1, "aide_limitee", 200, 2)]
    assert ecarts(UKR, pts) == []


def test_un_changement_de_cran_fait_un_ecart_mesure():
    pts = [_p(1, "contre_aide", 0, 1), _p(1, "aide_limitee", 400, 2)]
    (e,) = ecarts(UKR, pts)
    assert (e.avant.post_id, e.apres.post_id, e.ampleur) == (1, 2, 2)


def test_un_aller_retour_fait_deux_ecarts():
    pts = [_p(1, "60_tous", 0, 1), _p(1, "62", 100, 2), _p(1, "60_tous", 300, 3)]
    assert [(e.avant.post_id, e.apres.post_id) for e in ecarts(RET, pts)] == [(1, 2), (2, 3)]


def test_deux_positions_trop_rapprochees_ne_comptent_pas():
    # À dix jours, c'est une nuance de formulation : la référence reste la
    # position qui tenait, et la suivante s'y compare.
    pts = [_p(1, "60_tous", 0, 1), _p(1, "62", 10, 2), _p(1, "60_tous", 200, 3)]
    assert ecarts(RET, pts) == []


def test_les_figures_ne_se_melangent_pas():
    pts = [_p(1, "60_tous", 0, 1), _p(2, "64_ou_plus", 100, 2)]
    assert ecarts(RET, pts) == []


def test_un_code_hors_echelle_est_ignore():
    pts = [_p(1, "60_tous", 0, 1), _p(1, "65_ans", 100, 2)]
    assert ecarts(RET, pts) == []


TWEET = "Nous rétablirons la retraite à 60 ans pour tous les Français. C'est une question de justice."


def test_valider_garde_une_position_dont_le_verbatim_est_dans_le_tweet():
    lue = PositionLue(prend_position=True, position="60_tous", certitude="explicite",
                      verbatim="Nous rétablirons la retraite à 60 ans pour tous les Français.")
    assert valider(RET, lue, TWEET)[0] == "60_tous"


def test_valider_refuse_un_verbatim_reecrit():
    lue = PositionLue(prend_position=True, position="60_tous", certitude="explicite",
                      verbatim="Le RN veut la retraite à 60 ans pour tous.")
    assert valider(RET, lue, TWEET) == (None, None, None)


def test_valider_refuse_un_cran_invente():
    lue = PositionLue(prend_position=True, position="59_ans", certitude="explicite",
                      verbatim="Nous rétablirons la retraite à 60 ans pour tous les Français.")
    assert valider(RET, lue, TWEET) == (None, None, None)


def test_le_prompt_ne_contient_que_le_texte_et_la_question():
    p = prompt_for(RET, TWEET, cite="Texte cité")
    assert RET.question in p and TWEET in p and "contexte seulement" in p
    assert "Locuteur" not in p
