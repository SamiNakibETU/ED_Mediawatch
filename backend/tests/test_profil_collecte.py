"""Audience des comptes : chaque figure garde la sienne, même collectée en parallèle."""

import asyncio

from sqlalchemy import select

from src.config import get_settings
from src.database import get_engine, get_session_factory, init_db
from src.models.personality import Personality
from src.services.collection import x_collector

_CACHES = (get_settings, get_engine, get_session_factory)


class _Synd:
    """Client partagé, comme le vrai : `last_profile` vaut pour le dernier appel."""

    def __init__(self):
        self.last_profile = None

    async def collect(self, handle):
        await asyncio.sleep(0.01 if handle == "J_Bardella" else 0)
        if handle == "J_Bardella":
            self.last_profile = {"x_user_id": "1", "followers_count": 641566,
                                 "statuses_count": 25270, "x_protected": False}
            return [{"guid": "b1", "url": "https://x.com/J_Bardella/status/1", "content": "Un tweet."}]
        self.last_profile = None  # compte disparu : timeline vide, pas de profil
        return []


async def _repli_lent(**_):
    await asyncio.sleep(0.05)  # pendant ce temps, l'autre compte est collecté
    return {"inserted": 0}


def _run(tmp_path, monkeypatch, coro):
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path / 'p.db'}")
    for c in _CACHES:
        c.cache_clear()
    try:
        return asyncio.run(coro())
    finally:
        for c in _CACHES:
            c.cache_clear()


def test_un_compte_disparu_ne_prend_pas_l_audience_d_un_autre(tmp_path, monkeypatch):
    monkeypatch.setattr(x_collector, "SyndicationClient", _Synd)
    monkeypatch.setattr(x_collector, "run_archive_backfill", _repli_lent)

    async def go():
        await init_db()
        async with get_session_factory()() as db:
            # Vardon : jamais lu. Rambaud : porte déjà une audience lue par erreur.
            db.add(Personality(full_name="Philippe Vardon", handle="philippevardon", group_code="FIGURE"))
            db.add(Personality(full_name="Stéphane Rambaud", handle="stephan1Rambaud", group_code="RN",
                               followers_count=399455, statuses_count=182357))
            db.add(Personality(full_name="Jordan Bardella", handle="J_Bardella", group_code="RN"))
            await db.commit()
        await x_collector.run_collection(use_html=False)
        async with get_session_factory()() as db:
            return {p.handle: p.followers_count for p in (await db.execute(select(Personality))).scalars()}

    audience = _run(tmp_path, monkeypatch, go)
    assert audience == {"philippevardon": None, "stephan1Rambaud": None, "J_Bardella": 641566}


def test_un_compte_renomme_garde_sa_fiche_et_perd_l_audience_lue_sous_l_ancien_nom(tmp_path, monkeypatch):
    from src.scripts.seed_pool import ensure_renommes

    async def go():
        await init_db()
        async with get_session_factory()() as db:
            db.add(Personality(full_name="Jean Messiha", handle="MessihaOfficiel", group_code="FIGURE",
                               followers_count=250322))
            await db.commit()
        faits = await ensure_renommes()
        encore = await ensure_renommes()
        async with get_session_factory()() as db:
            (p,) = (await db.execute(select(Personality))).scalars()
            return faits, encore, p.handle, p.followers_count

    faits, encore, handle, abonnes = _run(tmp_path, monkeypatch, go)
    assert faits == {"MessihaOfficiel": "JeanMessiha"} and encore == {}
    assert (handle, abonnes) == ("JeanMessiha", None)
