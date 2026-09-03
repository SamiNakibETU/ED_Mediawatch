"""Ce qui compte se mesure par locuteur, jamais en brut.

Le produit prenait l'exhaustivité pour la valeur : 8 420 déclarations en
vitrine, sans qu'aucune vue ne dise ce qui compte. Les signaux étaient en base
depuis le début — likes, retweets, abonnés, reprise presse, contradiction — et
personne ne les lisait. La méthode adoptée (CheckThat!) place une étape de
priorisation entre la détection et le rapprochement ; on l'avait sautée.

La règle qui décide, mesurée sur le corpus : Damien Rieu fait 17 000 likes en
médiane, Marine Le Pen 2 100, Éric Ciotti 72. Les likes bruts classeraient un
militant devant la cheffe du parti. Ce qui compte, c'est l'inhabituel POUR CE
LOCUTEUR.
"""

import math
from datetime import datetime, timedelta, timezone

from src.services.analysis.relevance import (
    POIDS,
    audience_brute,
    audience_normalisee,
    portee,
    pourquoi,
    recence,
    score,
)


def test_a_modest_tweet_that_is_unusual_for_its_author_beats_a_viral_routine():
    """Ciotti à 800 likes (médiane 72) est un signal ; Rieu à 17 000 (sa
    médiane) n'en est pas un. Les likes bruts diraient l'inverse."""
    ciotti = audience_normalisee(audience_brute(800, 0, 0),
                                 mediane=audience_brute(72, 0, 0), ecart=0.9)
    rieu = audience_normalisee(audience_brute(17_000, 0, 0),
                               mediane=audience_brute(17_458, 0, 0), ecart=0.9)
    assert ciotti > 1.5
    assert rieu == 0.0, "la routine d'un compte, même énorme, vaut zéro"


def test_audience_is_bounded_so_one_viral_post_cannot_dominate():
    """Sans borne, un tweet à un million de relais écraserait toute
    contradiction, toute reprise presse : le score redeviendrait un compteur
    de likes avec un détour."""
    z = audience_normalisee(audience_brute(1_800_000, 0, 0),
                            mediane=audience_brute(2_000, 0, 0), ecart=0.5)
    assert z == 3.0


def test_a_retweet_weighs_two_likes_and_a_quote_three():
    """Le retweet relaie, la citation prend position : trois gestes, trois
    intensités. Les additionner à plat effacerait la différence."""
    assert audience_brute(0, 1, 0) == audience_brute(2, 0, 0)
    assert audience_brute(0, 0, 1) == audience_brute(3, 0, 0)


def test_reach_is_logarithmic_and_capped():
    """Trois millions d'abonnés ne valent pas mille fois trois mille. La portée
    pèse, elle ne décide pas seule."""
    assert 0.85 < portee(3_000_000) <= 1.0
    assert 0.5 < portee(10_000) < 0.6
    assert portee(None) == 0.0


def test_a_detected_contradiction_outweighs_any_single_audience_signal():
    """Priorité éditoriale : un propos qui en contredit un autre est le
    matériau même de l'observatoire. Il passe devant un tweet simplement
    beaucoup relayé."""
    contredit = score({"contradiction": 1.0, "recence": 1.0})
    tres_relaye = score({"audience": 2.0, "recence": 1.0})
    assert contredit > tres_relaye
    assert POIDS["contradiction"] > POIDS["presse"] > POIDS["audience"]


def test_recency_decays_over_a_month_and_never_goes_negative():
    now = datetime(2026, 9, 3, tzinfo=timezone.utc)
    assert recence(now, now) == 1.0
    assert math.isclose(recence(now - timedelta(days=30), now), math.exp(-1), rel_tol=1e-6)
    assert recence(None, now) == 0.0
    assert recence(now + timedelta(days=5), now) == 1.0, "une date future ne remonte pas"


def test_the_reasons_are_written_in_plain_french_and_in_order_of_weight():
    """Le pourquoi est ce que la page affiche. Sans lui le classement est une
    boîte noire, et un lecteur ne peut pas contester une boîte noire."""
    raisons = pourquoi({"contradiction": 1.0, "presse": 1.0, "audience": 2.2},
                       brut_audience=6443, facteur=3.2, confirmee=False)
    # U+202F : l'espace fine insécable, séparateur de milliers correct en
    # français — et insécable, pour que « 6 443 » ne se coupe jamais en bout de
    # ligne dans la page.
    assert raisons == ["contredit un autre propos", "reprise dans la presse",
                       "relayée 6 443 fois, 3× sa moyenne"]
    assert pourquoi({"audience": 0.4}, brut_audience=50, facteur=1.1, confirmee=False) == [], \
        "une audience de routine ne se mentionne pas"
    assert "confirmé" in pourquoi({"contradiction": 1.5}, brut_audience=0,
                                  facteur=0, confirmee=True)[0]


# ── Inhabituel n'est pas pertinent ──────────────────────────────────────────


def test_a_speech_outside_public_policy_is_demoted_whatever_its_audience():
    """Vu en une : « accueilli mon ami à la mairie de Nice », 16× la moyenne de
    son auteur. Le codage thématique dit « aucun objet d'action publique » ;
    ce jugement doit peser plus que l'audience. Un observatoire du discours
    politique ne met pas l'agenda d'un maire en tête."""
    from src.services.analysis.relevance import HORS_SUJET_FACTEUR

    signaux = {"audience": 3.0, "portee": 0.8, "recence": 1.0}
    assert score(signaux, hors_sujet=True) < score(signaux) * 0.5
    assert HORS_SUJET_FACTEUR < 0.5


def test_a_tiny_absolute_audience_is_never_unusual():
    """Un locuteur à 72 de médiane fait « 5× sa moyenne » avec 370 relais, vus
    par personne. Le z-score mesure l'écart, pas l'ampleur : sous un plancher
    d'ampleur, il ne dit rien et ne doit rien dire."""
    from src.services.analysis.relevance import AUDIENCE_PLANCHER

    assert AUDIENCE_PLANCHER >= 300
    # La fonction de normalisation ne connaît pas le plancher : c'est l'appelant
    # qui ne la consulte pas en dessous. On garde la constante sous test pour
    # que baisser le plancher soit un choix et non un accident.
