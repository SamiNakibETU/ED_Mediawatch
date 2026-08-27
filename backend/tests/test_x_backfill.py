"""Backfill X : identifiants via Wayback CDX, contenu via fxtwitter (hors ligne)."""

import asyncio

import httpx
import pytest

from src.services.collection import x_backfill
from src.services.collection.x_backfill import _fx_to_post, _id_prefixes, list_archived_ids, snowflake_floor

@pytest.fixture(autouse=True)
def _no_cdx_pause(monkeypatch):
    monkeypatch.setattr(x_backfill, "CDX_PAUSE_SECONDS", 0)


CDX_BODY = """https://x.com/J_Bardella/status/2082851860407255094
https://x.com/J_Bardella/status/2082851860407255094/photo/1
https://x.com/J_Bardella/status/2082851860407255094?lang=ro
https://x.com/J_Bardella/status/2070086009757323463?lang=vi
https://x.com/J_Bardella/status/1906659577174589915?ref_src=twsrc%5Etfw
"""


def test_cdx_ids_deduplicated_and_ordered():
    async def run():
        transport = httpx.MockTransport(lambda req: httpx.Response(200, text=CDX_BODY))
        async with httpx.AsyncClient(transport=transport) as c:
            return await list_archived_ids(c, "J_Bardella", since_year=2025, limit=10)
    ids = asyncio.run(run())
    # Variantes photo/?lang=/ref_src d'un même statut → un seul identifiant ;
    # tri du plus récent au plus ancien (snowflake = horodatage).
    assert ids == ["2082851860407255094", "2070086009757323463", "1906659577174589915"]


def test_snowflake_year_filter_uses_tweet_date_not_capture_date():
    # 1906659577174589915 = mars 2025 ; 1099306494347149313 = fév. 2019.
    body = CDX_BODY + "https://x.com/J_Bardella/status/1099306494347149313\n"
    async def run():
        transport = httpx.MockTransport(lambda req: httpx.Response(200, text=body))
        async with httpx.AsyncClient(transport=transport) as c:
            return await list_archived_ids(c, "J_Bardella", since_year=2025, limit=10)
    ids = asyncio.run(run())
    assert "1099306494347149313" not in ids          # 2019 exclu
    assert ids[0] == "2082851860407255094"           # le plus récent d'abord
    assert snowflake_floor(2023) < 1906659577174589915 < snowflake_floor(2026)


def test_cdx_failure_yields_empty():
    async def run():
        transport = httpx.MockTransport(lambda req: httpx.Response(503))
        async with httpx.AsyncClient(transport=transport) as c:
            return await list_archived_ids(c, "X", since_year=2026, limit=10)
    assert asyncio.run(run()) == []


FX = {
    "code": 200,
    "tweet": {
        "id": "2082851860407255094",
        "url": "https://x.com/J_Bardella/status/2082851860407255094",
        "text": "En régularisant des centaines de milliers de clandestins…",
        "created_at": "Thu Jul 30 15:32:35 +0000 2026",
        "likes": 16702, "retweets": 3082, "replies": 900, "views": 931538,
        "lang": "fr",
        "author": {"screen_name": "J_Bardella"},
        "quote": {"url": "https://x.com/AFP/status/1", "text": "Dépêche…",
                  "author": {"screen_name": "AFP"}},
        "replying_to": None,
        "media": {"all": [{"url": "https://pbs.twimg.com/media/x.jpg"}]},
    },
}


def test_fx_normalization():
    p = _fx_to_post(FX, "J_Bardella")
    assert p["post_type"] == "quote" and p["is_retweet"] is False
    assert p["published_at"].isoformat() == "2026-07-30T15:32:35+00:00"
    assert (p["likes"], p["retweets"], p["views"]) == (16702, 3082, 931538)
    assert p["quoted_handle"] == "AFP" and p["quoted_content"] == "Dépêche…"
    assert p["media_url"].endswith("x.jpg")
    assert p["collected_via"] == "fxtw"


def test_fx_other_author_is_retweet():
    data = {"tweet": dict(FX["tweet"], author={"screen_name": "MLP_officiel"}, quote=None)}
    p = _fx_to_post(data, "J_Bardella")
    assert p["is_retweet"] is True and p["post_type"] == "retweet"


def test_fx_same_guid_as_syndication():
    # Le même statut, collecté par les deux voies, doit se dédupliquer.
    from src.services.collection.x_syndication import _tweet_dict
    synd = _tweet_dict({
        "id_str": "2082851860407255094", "full_text": "x", "entities": {},
        "user": {"screen_name": "J_Bardella"},
        "created_at": "Thu Jul 30 15:32:35 +0000 2026",
    }, "J_Bardella")
    assert _fx_to_post(FX, "J_Bardella")["guid"] == synd["guid"]


def test_fx_empty_is_none():
    assert _fx_to_post({"tweet": {"id": "1", "text": ""}}, "X") is None
    assert _fx_to_post({}, "X") is None


def test_id_prefixes_cover_period():
    # 2023 → ids ≥ 1.6e18 ; aujourd'hui (2026) → ids ≈ 2.09e18 : préfixes 16..20.
    pfx = _id_prefixes(2023)
    assert pfx[0] == "16" and "19" in pfx and pfx[-1] >= "20"
    assert _id_prefixes(2026)[0] == "20"


def test_cdx_queries_both_domains_and_prefixes():
    calls = []
    def handler(req):
        calls.append(req.url.params["url"])
        return httpx.Response(200, text=CDX_BODY)
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
            return await list_archived_ids(c, "J_Bardella", since_year=2026, limit=10)
    ids = asyncio.run(run())
    assert any(u.startswith("x.com/") for u in calls) and any(u.startswith("twitter.com/") for u in calls)
    assert all("/status/" in u and u.endswith("*") for u in calls)
    assert ids and ids[0] == "2082851860407255094"


def test_quota_spread_across_time_slices():
    # 2 tranches : une riche (préfixe 20 = 2025-26), une pauvre (19 = 2024-25).
    rich = "\n".join(f"https://x.com/H/status/20{i:017d}" for i in range(50))
    poor = "\n".join(f"https://x.com/H/status/19{i:017d}" for i in range(3))
    def handler(req):
        u = req.url.params["url"]
        return httpx.Response(200, text=rich if "/20*" in u else (poor if "/19*" in u else ""))
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
            return await list_archived_ids(c, "H", since_year=2024, limit=10)
    ids = asyncio.run(run())
    assert len(ids) == 10
    assert sum(1 for i in ids if i.startswith("19")) == 3   # toute la tranche pauvre
    assert sum(1 for i in ids if i.startswith("20")) == 7   # reliquat à la riche
