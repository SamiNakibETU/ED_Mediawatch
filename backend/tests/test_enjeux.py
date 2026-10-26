"""Registre des positions : le tri, la validation, et le calcul des écarts."""

from datetime import datetime, timedelta, timezone

from src.services.analysis.enjeux import ENJEUX, PAR_SLUG, THEMES, Point, ecarts
from src.services.analysis.registre import DeclLue, pretri, prompt_extraction, valider

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
        assert e.question.endswith("?") and e.theme in THEMES


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
PHRASE = "Nous rétablirons la retraite à 60 ans pour tous les Français."


def test_valider_garde_une_declaration_dont_le_verbatim_est_dans_le_tweet():
    d = DeclLue(enjeu="retraites", position="60_tous", modalite="promet", verbatim=PHRASE)
    assert valider(d, TWEET).position == "60_tous"


def test_valider_refuse_un_verbatim_reecrit():
    d = DeclLue(enjeu="retraites", position="60_tous", verbatim="Le RN veut la retraite à 60 ans pour tous.")
    assert valider(d, TWEET) is None


def test_un_cran_invente_passe_hors_liste_sans_position():
    d = DeclLue(enjeu="retraites", position="59_ans", verbatim=PHRASE)
    v = valider(d, TWEET)
    assert v.enjeu == "hors_liste" and v.position is None and v.objet


def test_hors_liste_exige_un_objet():
    assert valider(DeclLue(enjeu="hors_liste", verbatim=PHRASE), TWEET) is None
    assert valider(DeclLue(enjeu="hors_liste", objet="justice sociale", verbatim=PHRASE), TWEET).objet


class _Post:
    def __init__(self, content, **kw):
        self.content, self.is_retweet, self.post_type = content, kw.get("rt", False), kw.get("type", "original")
        self.lang, self.quoted_content = kw.get("lang", "fr"), kw.get("cite")
        self.published_at = T0


def test_le_pretri_ecarte_sans_appel_ce_qui_ne_peut_pas_porter_de_position():
    assert pretri(_Post(TWEET, rt=True)) == "retweet"
    assert pretri(_Post("Merci à tous ! https://t.co/x #RN")) == "trop_court"
    assert pretri(_Post("We will never accept this deal with the European Union.", lang="en")) == "langue"
    assert pretri(_Post(TWEET)) is None


def test_le_prompt_ne_donne_ni_le_nom_ni_le_compte_de_l_auteur():
    p = prompt_extraction([_Post(TWEET, cite="Texte cité")])
    assert TWEET in p and "écrit par quelqu'un d'autre" in p and "2022-03-01" in p
    assert "@" not in p


def test_le_nettoyage_recolle_les_mots_coupes_en_fin_de_ligne():
    from src.services.analysis.programme import nettoyer
    assert nettoyer("La loi de programmation prévoi-\nra que 85.000 places\nde prison") == \
        "La loi de programmation prévoira que 85.000 places de prison"
    assert nettoyer("travaux d’in -\ntérêt général") == "travaux d’intérêt général"


def test_un_ecart_n_est_retenu_que_si_les_deux_juges_le_tiennent_pour_reel():
    from src.services.analysis.ecarts import Verdict, decision_auto
    reel = Verdict(type="revirement", force=3)
    assert decision_auto(reel, Verdict(type="glissement", force=2)) == "retenu"
    assert decision_auto(reel, Verdict(type="nuance", force=0)) == "faible"
    assert decision_auto(reel, None) == "faible"
    assert decision_auto(reel, Verdict(type="erreur_de_lecture", force=0)) == "ecarte"


def test_un_verbatim_trop_court_ne_porte_pas_de_position():
    d = DeclLue(enjeu="ukraine", position="contre_aide", verbatim="Halte au fou !")
    assert valider(d, "Halte au fou ! On ne fait pas la guerre à une puissance nucléaire.") is None


def test_l_import_zeeschuimer_lit_le_texte_long_et_le_tweet_cite():
    import json
    from src.services.collection.x_zeeschuimer import lire
    auteur = {"core": {"user_results": {"result": {"core": {"screen_name": "J_Bardella"}}}}}
    cite = {"rest_id": "2", "legacy": {"id_str": "2", "full_text": "Texte cité", "created_at": "Mon Jun 10 08:00:00 +0000 2024"},
            "core": {"user_results": {"result": {"core": {"screen_name": "MLP_officiel"}}}}}
    tw = {"data": {"rest_id": "1", **auteur, "quoted_status_result": {"result": cite},
                   "note_tweet": {"note_tweet_results": {"result": {"text": "Un texte long qui dépasse 280 signes."}}},
                   "legacy": {"id_str": "1", "full_text": "Un texte coupé", "created_at": "Tue Jun 11 08:00:00 +0000 2024"}}}
    tweets, illisibles = lire(json.dumps(tw) + "\n" + "pas du json\n")
    assert illisibles == 1
    (a1, d1), (a2, d2) = tweets
    assert a1 == "J_Bardella" and d1["content"].startswith("Un texte long") and d1["post_type"] == "quote"
    assert d1["quoted_handle"] == "MLP_officiel" and a2 == "MLP_officiel"
