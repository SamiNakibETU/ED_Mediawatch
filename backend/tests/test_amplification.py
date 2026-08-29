"""Trois actes de parole, trois traitements. Les confondre détruit l'information.

La règle qui protège tout : un retweet simple ne devient JAMAIS une déclaration.
Ce ne sont pas les mots de la figure — `content` porte le texte d'origine — et
les lui attribuer serait la même faute que prêter à quelqu'un les propos qu'un
journal cite, en plus invisible : le texte a l'air d'un post comme un autre.

La distinction retweet / citation n'est pas une subtilité de collecte. La
méta-analyse des travaux sur Twitter conclut que le relais nu indique très
majoritairement l'adhésion, tandis que le relais commenté sert des signaux
variés — approbation comme dénonciation. Mesuré sur ce corpus : Marine Le Pen
cite BFMTV dix fois et ne le relaie jamais ; Sébastien Chenu relaie quinze fois
Marine Le Pen sans jamais commenter. Additionner les deux effacerait exactement
ce qui se voit là.
"""

import asyncio
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from src.config import get_settings
from src.database import get_engine, get_session_factory, init_db
from src.models.amplification import Amplification
from src.models.personality import Personality
from src.models.post import Post
from src.pipeline.stages import BY_NAME, FREE
from src.services.analysis.amplification import (
    build_amplifications, new_voices, who_they_amplify,
)

_CACHES = (get_settings, get_engine, get_session_factory)
BASE = datetime(2026, 6, 1, tzinfo=timezone.utc)


def _run(tmp_path, monkeypatch, posts, check, db_name="ampli.db"):
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path / db_name}")
    for c in _CACHES:
        c.cache_clear()

    async def go():
        await init_db()
        factory = get_session_factory()
        async with factory() as db:
            p = Personality(full_name="Sébastien Chenu", handle="sebchenu",
                            group_code="RN")
            db.add(p)
            await db.commit()
            await db.refresh(p)
            for i, (kind, cible, quand) in enumerate(posts):
                db.add(Post(
                    personality_id=p.id, guid=f"g{i}", url=f"https://x.com/s/{i}",
                    content=f"Texte {i}", post_type=kind,
                    is_retweet=kind == "retweet",
                    quoted_handle=cible,
                    quoted_url=f"https://x.com/{cible}/status/{i}" if cible else None,
                    published_at=quand,
                ))
            await db.commit()
        await check(factory, p.id)

    try:
        asyncio.run(go())
    finally:
        for c in _CACHES:
            c.cache_clear()


def test_the_three_acts_are_treated_differently(tmp_path, monkeypatch):
    """Original et réponse ne produisent aucune arête : publier n'est pas
    relayer, et répondre à quelqu'un ne l'est pas davantage."""
    posts = [
        ("original", None, BASE),
        ("reply", None, BASE),
        ("retweet", "MLP_officiel", BASE),
        ("quote", "BFMTV", BASE),
    ]

    async def check(factory, pid):
        stats = await build_amplifications()
        assert stats["retweets"] == 1 and stats["quotes"] == 1
        async with factory() as db:
            kinds = sorted((await db.execute(
                select(Amplification.kind))).scalars().all())
        assert kinds == ["quote", "retweet"]

    _run(tmp_path, monkeypatch, posts, check)


def test_relay_and_comment_are_counted_apart(tmp_path, monkeypatch):
    """« 15 relayés » et « 15 commentés » ne disent pas la même chose : le
    premier vaut adhésion, le second peut être une attaque."""
    posts = [("retweet", "MLP_officiel", BASE)] * 3 + \
            [("quote", "MLP_officiel", BASE)] * 2

    async def check(factory, pid):
        await build_amplifications()
        rows = await who_they_amplify(pid)
        assert len(rows) == 1
        assert rows[0]["n"] == 5
        assert rows[0]["n_retweets"] == 3 and rows[0]["n_quotes"] == 2

    _run(tmp_path, monkeypatch, posts, check)


def test_a_post_produces_at_most_one_edge(tmp_path, monkeypatch):
    """Sans unicité, chaque passe du pipeline doublerait le graphe et toutes
    les tendances seraient fausses."""
    posts = [("retweet", "MLP_officiel", BASE), ("quote", "BFMTV", BASE)]

    async def check(factory, pid):
        await build_amplifications()
        second = await build_amplifications()
        assert second["created"] == 0
        async with factory() as db:
            n = len((await db.execute(select(Amplification))).scalars().all())
        assert n == 2

    _run(tmp_path, monkeypatch, posts, check)


def test_a_relay_without_target_stays_out(tmp_path, monkeypatch):
    """La collecte ne retrouve pas toujours le compte relayé. Une arête sans
    cible ne relie rien : mieux vaut la compter à part que la fabriquer."""
    posts = [("retweet", None, BASE), ("retweet", "MLP_officiel", BASE)]

    async def check(factory, pid):
        stats = await build_amplifications()
        assert stats["created"] == 1
        assert stats["without_target"] == 1

    _run(tmp_path, monkeypatch, posts, check)


def test_a_new_voice_needs_a_corpus_that_covers_before(tmp_path, monkeypatch):
    """Une figure entrée dans le corpus il y a deux mois aurait toutes ses voix
    « nouvelles ». Sans ce garde-fou, un début de collecte passerait pour un
    changement de comportement — l'inverse d'un résultat."""
    récent = datetime.now(timezone.utc) - timedelta(days=10)
    posts = [("retweet", "compte_radical", récent)] * 3

    async def check(factory, pid):
        await build_amplifications()
        # Le corpus commence en même temps que le relais : rien à conclure.
        assert await new_voices(days=90, min_relays=2) == []

    _run(tmp_path, monkeypatch, posts, check)


def test_a_genuinely_new_voice_is_surfaced(tmp_path, monkeypatch):
    """Le cas utile : un corpus qui couvre l'année, et un compte apparu il y a
    peu. C'est un déplacement, daté et sourcé — on le montre sans dire ce
    qu'il signifie."""
    vieux = datetime.now(timezone.utc) - timedelta(days=300)
    récent = datetime.now(timezone.utc) - timedelta(days=10)
    posts = [("retweet", "compte_habituel", vieux)] * 2 + \
            [("retweet", "compte_nouveau", récent)] * 3

    async def check(factory, pid):
        await build_amplifications()
        voix = await new_voices(days=90, min_relays=2)
        assert [v["handle"] for v in voix] == ["compte_nouveau"]
        assert voix[0]["n"] == 3

    _run(tmp_path, monkeypatch, posts, check)


def test_a_single_relay_is_not_a_trend(tmp_path, monkeypatch):
    """Un relais isolé peut être un accident de lecture, pas un ralliement."""
    vieux = datetime.now(timezone.utc) - timedelta(days=300)
    récent = datetime.now(timezone.utc) - timedelta(days=5)
    posts = [("retweet", "habituel", vieux)] * 2 + [("retweet", "vu_une_fois", récent)]

    async def check(factory, pid):
        await build_amplifications()
        assert await new_voices(days=90, min_relays=2) == []

    _run(tmp_path, monkeypatch, posts, check)


def test_building_the_graph_costs_nothing():
    """Aucun appel de modèle : la typologie est en base et la cible vient de la
    collecte. Une étape payante ici serait un défaut de conception."""
    assert BY_NAME["amplifications"].cost == FREE
    assert "collect_x" in BY_NAME["amplifications"].depends_on
