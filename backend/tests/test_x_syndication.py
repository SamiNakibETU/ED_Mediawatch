"""Parseur de la syndication X (widgets embarqués) — voie primaire post-Nitter.

Le JSON `__NEXT_DATA__` porte texte intégral, engagement, RT/quote/réponse. Les
tests fixent le contrat de normalisation vers `_insert_new` : un RT porte le
texte d'origine, une citation garde le tweet cité, les t.co sont dépliés, et
une page sans données ne produit rien (repli Nitter possible).
"""

import json

from src.services.collection.x_syndication import parse_syndication

_USER = {"screen_name": "J_Bardella", "name": "Jordan Bardella"}


def _page(entries: list[dict]) -> str:
    payload = {"props": {"pageProps": {"timeline": {"entries": entries}}}}
    return (
        '<html><script id="__NEXT_DATA__" type="application/json">'
        + json.dumps(payload) + "</script></html>"
    )


def _entry(**tweet) -> dict:
    base = {
        "id_str": "2091800582042333264",
        "created_at": "Mon Aug 24 08:11:37 +0000 2026",
        "full_text": "Texte du tweet https://t.co/abc",
        "entities": {"urls": [{"url": "https://t.co/abc",
                               "expanded_url": "https://example.org/article"}]},
        "favorite_count": 1239, "retweet_count": 220,
        "reply_count": 40, "quote_count": 12, "lang": "fr", "user": _USER,
    }
    base.update(tweet)
    return {"content": {"tweet": base}}


def test_original_tweet_normalized():
    posts = parse_syndication(_page([_entry()]), "J_Bardella")
    assert len(posts) == 1
    p = posts[0]
    assert p["url"] == "https://x.com/J_Bardella/status/2091800582042333264"
    assert p["post_type"] == "original"
    assert p["is_retweet"] is False and p["is_reply"] is False
    assert p["content"] == "Texte du tweet https://example.org/article"  # t.co déplié
    assert p["published_at"].isoformat() == "2026-08-24T08:11:37+00:00"
    assert (p["likes"], p["retweets"], p["replies"], p["quotes"]) == (1239, 220, 40, 12)
    assert p["collected_via"] == "synd"
    assert p["lang"] == "fr"


def test_retweet_carries_original_text():
    rt = _entry(
        full_text="RT @K_Pfeffer: Le sérieux du Canard…",
        retweeted_status={"id_str": "1", "full_text": "Le sérieux du Canard enchaîné est en cause.",
                          "entities": {}, "user": {"screen_name": "K_Pfeffer"}},
    )
    p = parse_syndication(_page([rt]), "J_Bardella")[0]
    assert p["post_type"] == "retweet" and p["is_retweet"] is True
    assert p["content"] == "Le sérieux du Canard enchaîné est en cause."


def test_quote_keeps_quoted_tweet():
    q = _entry(quoted_status={
        "id_str": "99", "full_text": "On nous répète que la dette serait un mur.",
        "entities": {}, "user": {"screen_name": "MPigasse"},
    })
    p = parse_syndication(_page([q]), "J_Bardella")[0]
    assert p["post_type"] == "quote"
    assert p["quoted_handle"] == "MPigasse"
    assert p["quoted_url"] == "https://x.com/MPigasse/status/99"
    assert "mur" in p["quoted_content"]


def test_reply_is_typed_and_linked():
    r = _entry(in_reply_to_screen_name="MLP_officiel", in_reply_to_status_id_str="77")
    p = parse_syndication(_page([r]), "J_Bardella")[0]
    assert p["post_type"] == "reply" and p["is_reply"] is True
    assert p["reply_to_handle"] == "MLP_officiel"
    assert p["reply_to_url"] == "https://x.com/MLP_officiel/status/77"


def test_same_tweet_same_guid():
    a = parse_syndication(_page([_entry()]), "J_Bardella")[0]
    b = parse_syndication(_page([_entry(favorite_count=9999)]), "J_Bardella")[0]
    assert a["guid"] == b["guid"]  # dédup par identifiant, pas par engagement


def test_page_without_data_yields_nothing():
    assert parse_syndication("<html>rate limited</html>", "J_Bardella") == []
    assert parse_syndication(_page([{"content": {}}]), "J_Bardella") == []


def test_timeline_state_distinguishes_empty_accounts():
    from src.services.collection.x_syndication import _is_cloudflare_html, timeline_state
    assert timeline_state(_page([_entry()])) == "ok"
    assert timeline_state(_page([])) == "empty"          # protégé / suspendu / muet
    assert timeline_state("<html>rate limited</html>") == "empty"
    assert _is_cloudflare_html("<!DOCTYPE html><title>Attention Required! | Cloudflare</title>")
    assert not _is_cloudflare_html('{"ok":true}')


def test_video_media_picks_best_mp4():
    from src.services.collection.x_syndication import _media_url
    t = {"extended_entities": {"media": [{
        "type": "video", "media_url_https": "https://pbs.twimg.com/thumb.jpg",
        "video_info": {"variants": [
            {"content_type": "application/x-mpegURL", "url": "https://v/m3u8"},
            {"content_type": "video/mp4", "bitrate": 256000, "url": "https://v/low.mp4"},
            {"content_type": "video/mp4", "bitrate": 832000, "url": "https://v/high.mp4"},
        ]}}]}}
    assert _media_url(t) == "https://v/high.mp4"
    photo = {"extended_entities": {"media": [{"type": "photo", "media_url_https": "https://pbs/p.jpg"}]}}
    assert _media_url(photo) == "https://pbs/p.jpg"


def test_parse_profile_reads_stable_id_and_audience():
    from src.services.collection.x_syndication import parse_profile
    u = dict(_USER, id_str="1499400284", followers_count=625565, statuses_count=24888, protected=False)
    prof = parse_profile(_page([_entry(user=u)]), "j_bardella")  # insensible à la casse
    assert prof == {"x_user_id": "1499400284", "followers_count": 625565,
                    "statuses_count": 24888, "x_protected": False}
    assert parse_profile("<html/>", "x") is None


def test_batch_rows_share_identical_keys():
    # Une citation et un tweet simple dans le même lot → mêmes clés, sinon
    # l'INSERT multi-VALUES rejette tout le lot du handle.
    quote = _entry(quoted_status={"id_str": "9", "full_text": "q", "entities": {},
                                  "user": {"screen_name": "AFP"}})
    rows = parse_syndication(_page([_entry(), quote]), "J_Bardella")
    assert set(rows[0].keys()) == set(rows[1].keys())
