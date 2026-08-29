"""Un retweet doit dire QUI il relaie.

Le parseur lisait `retweeted_status` pour en prendre le texte et jetait son
auteur. Résultat mesuré en base : 17 retweets sur 1 455 portaient une cible.
Un retweet sans cible n'est pas un signal d'amplification, c'est une ligne
morte — et tout le graphe d'amplification repose là-dessus.

Ces tests verrouillent aussi le piège qui va avec : pour un retweet, `content`
porte les mots de QUELQU'UN D'AUTRE. C'est la même classe d'erreur que
l'attribution de presse, et elle serait plus grave encore ici parce qu'elle est
invisible — le texte a l'air d'un post comme un autre.
"""

import json

from src.services.collection.x_backfill import _fx_to_post
from src.services.collection.x_syndication import parse_syndication


def _page(tweets: list[dict]) -> str:
    """Une page de syndication minimale, telle que X la rend."""
    data = {"props": {"pageProps": {"timeline": {
        "entries": [{"content": {"tweet": t}} for t in tweets]
    }}}}
    return ('<script id="__NEXT_DATA__" type="application/json">'
            + json.dumps(data) + "</script>")


def _tweet(tid: str, author: str, text: str, **extra) -> dict:
    return {
        "id_str": tid,
        "user": {"screen_name": author},
        "full_text": text,
        "created_at": "Wed Aug 26 09:00:00 +0000 2026",
        **extra,
    }


# ── Syndication ──────────────────────────────────────────────────────────

def test_retweet_carries_its_target():
    html = _page([
        _tweet("100", "MLP_officiel", "peu importe",
               retweeted_status=_tweet("77", "RNational_off", "Le texte relayé.")),
    ])
    posts = parse_syndication(html, "MLP_officiel")
    assert len(posts) == 1
    p = posts[0]
    assert p["post_type"] == "retweet"
    assert p["quoted_handle"] == "RNational_off"
    assert p["quoted_url"] == "https://x.com/RNational_off/status/77"


def test_quote_still_carries_its_target_and_its_own_words():
    """Le retweet cité porte DEUX choses : le commentaire, qui est de lui, et
    l'objet cité, qui ne l'est pas. Les confondre revient à lui prêter le
    propos qu'il commente."""
    html = _page([
        _tweet("200", "j_bardella", "Mon commentaire à moi.",
               quoted_status=_tweet("88", "unJournaliste", "Le tweet commenté.")),
    ])
    p = parse_syndication(html, "j_bardella")[0]
    assert p["post_type"] == "quote"
    assert p["content"] == "Mon commentaire à moi."
    assert p["quoted_handle"] == "unJournaliste"
    assert p["quoted_content"] == "Le tweet commenté."


def test_an_original_post_has_no_target():
    """Une cible posée sur un post original inventerait une amplification."""
    html = _page([_tweet("300", "sebchenu", "Une position à moi.")])
    p = parse_syndication(html, "sebchenu")[0]
    assert p["post_type"] == "original"
    assert p["quoted_handle"] is None
    assert p["quoted_url"] is None


def test_a_reply_is_not_an_amplification():
    """Répondre à quelqu'un n'est pas le relayer."""
    html = _page([
        _tweet("400", "knafo_sarah", "Non.",
               in_reply_to_screen_name="quelquun",
               in_reply_to_status_id_str="399"),
    ])
    p = parse_syndication(html, "knafo_sarah")[0]
    assert p["post_type"] == "reply"
    assert p["quoted_handle"] is None


def test_retweet_content_is_not_the_retweeters_words():
    """Piège documenté : pour un retweet, `content` porte le texte d'origine.
    L'extraction L0 exclut donc `is_retweet` — relâcher ce filtre prêterait à
    la figure les propos qu'elle relaie."""
    html = _page([
        _tweet("500", "MLP_officiel", "ignoré",
               retweeted_status=_tweet("77", "un_autre", "Les mots d'un autre.")),
    ])
    p = parse_syndication(html, "MLP_officiel")[0]
    assert p["content"] == "Les mots d'un autre."
    assert p["is_retweet"] is True      # le drapeau qui protège l'extraction


# ── fxtwitter (chemin de rattrapage) ─────────────────────────────────────

def test_fxtwitter_recovers_the_target_from_the_original_author():
    """fxtwitter rend un retweet sous son auteur d'origine : c'est de là que le
    script de rattrapage tire la cible des 1 438 retweets déjà collectés."""
    data = {"tweet": {
        "id": "77", "text": "Le texte relayé.",
        "author": {"screen_name": "RNational_off"},
        "url": "https://x.com/RNational_off/status/77",
        "created_timestamp": 1787000000,
    }}
    p = _fx_to_post(data, handle="MLP_officiel")
    assert p["is_retweet"] is True
    assert p["quoted_handle"] == "RNational_off"
    assert p["quoted_url"] == "https://x.com/RNational_off/status/77"


def test_fxtwitter_leaves_an_original_post_alone():
    data = {"tweet": {
        "id": "78", "text": "Ma position.",
        "author": {"screen_name": "MLP_officiel"},
        "url": "https://x.com/MLP_officiel/status/78",
        "created_timestamp": 1787000000,
    }}
    p = _fx_to_post(data, handle="MLP_officiel")
    assert p["is_retweet"] is False
    assert p["quoted_handle"] is None
