"""Troncature syndication (280 car.) : détection, slice display_text_range, enrichissement.

Cas réel : statut 2091204464795365548 — 304 caractères en syndication (280 +
lien), 501 chez fxtwitter (`is_note_tweet`). Une déclaration extraite d'un
texte coupé est fausse par omission ; on doit la refaire sur le texte entier.
"""

import asyncio
import json

import httpx
from sqlalchemy import select

from src.config import get_settings
from src.database import get_engine, get_session_factory, init_db
from src.models.claim import Claim
from src.models.personality import Personality
from src.models.post import Post
from src.services.collection import x_enrich
from src.services.collection.x_syndication import _tweet_dict

_CACHES = (get_settings, get_engine, get_session_factory)
_USER = {"screen_name": "J_Bardella"}


def test_display_text_range_slices_reply_mentions_and_media_link():
    t = {
        "id_str": "1", "user": _USER, "created_at": "Mon Aug 24 08:11:37 +0000 2026",
        "full_text": "@MLP_officiel Texte visible https://t.co/media",
        "display_text_range": [14, 27],
        "entities": {"urls": []}, "in_reply_to_screen_name": "MLP_officiel",
    }
    d = _tweet_dict(t, "J_Bardella")
    assert d["content"] == "Texte visible"
    assert d["text_truncated"] is False


def test_long_text_flagged_truncated():
    body = "x" * 279
    t = {"id_str": "2", "user": _USER, "created_at": "Mon Aug 24 08:11:37 +0000 2026",
         "full_text": body, "display_text_range": [0, 279], "entities": {}}
    assert _tweet_dict(t, "J_Bardella")["text_truncated"] is True


def test_short_text_not_flagged():
    t = {"id_str": "3", "user": _USER, "created_at": "Mon Aug 24 08:11:37 +0000 2026",
         "full_text": "Court.", "display_text_range": [0, 6], "entities": {}}
    assert _tweet_dict(t, "J_Bardella")["text_truncated"] is False


def test_unicode_range_is_codepoint_based():
    # Emojis = 1 point de code ; un slice par octets casserait le texte.
    t = {"id_str": "4", "user": _USER, "created_at": "Mon Aug 24 08:11:37 +0000 2026",
         "full_text": "🇫🇷 Vive la France https://t.co/x",
         "display_text_range": [0, 17], "entities": {}}
    assert _tweet_dict(t, "J_Bardella")["content"] == "🇫🇷 Vive la France"


def _fx(text: str) -> dict:
    return {"tweet": {"id": "2091204464795365548", "text": text,
                      "url": "https://x.com/J_Bardella/status/2091204464795365548",
                      "created_at": "Sat Aug 22 16:42:00 +0000 2026",
                      "author": {"screen_name": "J_Bardella"}, "lang": "fr"}}


def test_enrichment_expands_and_invalidates_claims(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path / 't.db'}")
    for c in _CACHES:
        c.cache_clear()
    full = "Texte intégral " * 30  # ~450 car.
    transport = httpx.MockTransport(lambda req: httpx.Response(200, text=json.dumps(_fx(full))))
    real_client = httpx.AsyncClient
    monkeypatch.setattr(x_enrich.httpx, "AsyncClient",
                        lambda **kw: real_client(transport=transport, **{k: v for k, v in kw.items() if k != "timeout"}))

    async def run():
        await init_db()
        f = get_session_factory()
        async with f() as db:
            p = Personality(full_name="Jordan Bardella", handle="J_Bardella", group_code="RN")
            db.add(p); await db.commit(); await db.refresh(p)
            post = Post(personality_id=p.id, guid="g1",
                        url="https://x.com/J_Bardella/status/2091204464407255094",
                        content="x" * 280, text_truncated=True, collected_via="synd")
            db.add(post); await db.commit(); await db.refresh(post)
            db.add(Claim(platform="x", post_id=post.id, verbatim="xxx", claim_type="normatif",
                         extraction_method="llm_segment", dedup_key="k"))
            await db.commit()
        stats = await x_enrich.enrich_truncated_posts()
        async with f() as db:
            post = (await db.execute(select(Post))).scalars().one()
            claims = (await db.execute(select(Claim))).scalars().all()
        assert stats["expanded"] == 1 and stats["claims_invalidated"] == 1
        assert post.content == full.strip() and post.text_truncated is False
        assert post.collected_via == "syndfx"
        assert claims == []  # à refaire par le L0 sur le texte entier

    try:
        asyncio.run(run())
    finally:
        for c in _CACHES:
            c.cache_clear()


def test_enrichment_keeps_genuinely_short_text(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path / 'u.db'}")
    for c in _CACHES:
        c.cache_clear()
    same = "y" * 280
    transport = httpx.MockTransport(lambda req: httpx.Response(200, text=json.dumps(_fx(same))))
    real_client = httpx.AsyncClient
    monkeypatch.setattr(x_enrich.httpx, "AsyncClient",
                        lambda **kw: real_client(transport=transport, **{k: v for k, v in kw.items() if k != "timeout"}))

    async def run():
        await init_db()
        f = get_session_factory()
        async with f() as db:
            p = Personality(full_name="X", handle="J_Bardella", group_code="RN")
            db.add(p); await db.commit(); await db.refresh(p)
            db.add(Post(personality_id=p.id, guid="g2", url="https://x.com/J_Bardella/status/2091204464407255094",
                        content=same, text_truncated=True, collected_via="synd"))
            await db.commit()
        stats = await x_enrich.enrich_truncated_posts()
        async with f() as db:
            post = (await db.execute(select(Post))).scalars().one()
        assert stats["expanded"] == 0
        assert post.text_truncated is False and post.collected_via == "synd"

    try:
        asyncio.run(run())
    finally:
        for c in _CACHES:
            c.cache_clear()


# ── Le moignon de lien laissé par la coupe à 280 ───────────────────────────


def test_a_cut_link_leaves_a_stump_that_reads_as_a_typo():
    """Vu dans le registre : « Bonne rentrée à tous ! 🇫🇷 h ».

    Un tweet coupé au milieu de son adresse finit par « h », « htt »,
    « https://t.c ». L'expansion des t.co ne peut rien y faire — le lien
    raccourci n'est plus reconnaissable — et la page attribue alors à la figure
    une faute de frappe qui est une faute de la collecte.
    """
    from src.services.collection.x_syndication import _trim_cut_link

    assert _trim_cut_link("Bonne rentrée à tous ! h", truncated=True) == \
        "Bonne rentrée à tous !"
    assert _trim_cut_link("c’est au peuple de décider. https://t.c",
                          truncated=True) == "c’est au peuple de décider."


def test_a_complete_tweet_ending_in_h_is_left_alone():
    """« Rendez-vous à 15 h » est un texte juste. Sans le drapeau de troncature
    pour trancher, la correction couperait des fins de phrase légitimes — et une
    citation amputée est plus grave qu'un moignon visible."""
    from src.services.collection.x_syndication import _trim_cut_link

    assert _trim_cut_link("Rendez-vous à 15 h", truncated=False) == \
        "Rendez-vous à 15 h"
    assert _trim_cut_link("Un texte entier, sans lien.", truncated=True) == \
        "Un texte entier, sans lien."
