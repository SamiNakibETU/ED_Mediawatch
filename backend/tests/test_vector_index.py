"""Index vectoriel : même interface, deux moteurs selon la base.

Ce que ces tests protègent : le rapprochement comparait chaque vecteur à tous
les autres en Python — ~1,5 million de cosinus par passe sur le corpus actuel,
inexploitable à 50 000 déclarations. Le calcul descend dans PostgreSQL (pgvector,
index HNSW) sans que la logique d'analyse change. Le repli force brute garde le
développement local possible sans Postgres.
"""

import asyncio

from sqlalchemy import select

from src.config import get_settings
from src.database import get_engine, get_session_factory, init_db
from src.models.claim import Claim
from src.services.analysis import vector_index as vi
from src.services.analysis.vector_index import (
    BruteForceIndex,
    PgVectorIndex,
    get_index,
    is_postgres,
    reset_index,
)

_CACHES = (get_settings, get_engine, get_session_factory)


def _fresh(tmp_path, monkeypatch, name):
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path / name}")
    for c in _CACHES:
        c.cache_clear()
    reset_index()


def test_backend_follows_the_database(monkeypatch):
    """Le choix du moteur n'est pas une option : il découle de la base."""
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@h/db")
    for c in _CACHES:
        c.cache_clear()
    reset_index()
    assert is_postgres() and isinstance(get_index(), PgVectorIndex)

    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///./x.db")
    for c in _CACHES:
        c.cache_clear()
    reset_index()
    assert not is_postgres() and isinstance(get_index(), BruteForceIndex)

    for c in _CACHES:
        c.cache_clear()
    reset_index()


def test_nearest_ranks_by_similarity(tmp_path, monkeypatch):
    _fresh(tmp_path, monkeypatch, "n.db")

    async def run():
        await init_db()
        factory = get_session_factory()
        async with factory() as db:
            for i, emb in enumerate((
                [1.0, 0.0, 0.0],    # identique à la requête
                [0.8, 0.6, 0.0],    # proche
                [0.0, 1.0, 0.0],    # orthogonal
            )):
                db.add(Claim(platform="x", verbatim=f"v{i}", claim_type="normatif",
                             embedding=emb, dedup_key=f"k{i}"))
            await db.commit()
            ids = [r for r in (await db.execute(select(Claim.id).order_by(Claim.id))).scalars()]

        got = await get_index().nearest([1.0, 0.0, 0.0], k=3)
        assert [i for i, _ in got] == [ids[0], ids[1], ids[2]]   # ordonné
        assert got[0][1] > got[1][1] > got[2][1]

    try:
        asyncio.run(run())
    finally:
        for c in _CACHES:
            c.cache_clear()
        reset_index()


def test_min_score_and_exclusions(tmp_path, monkeypatch):
    """Le seuil et les exclusions évitent de payer un appel LLM sur du bruit
    ou sur une paire déjà jugée."""
    _fresh(tmp_path, monkeypatch, "f.db")

    async def run():
        await init_db()
        factory = get_session_factory()
        async with factory() as db:
            for i, emb in enumerate(([1.0, 0.0, 0.0], [0.8, 0.6, 0.0], [0.0, 1.0, 0.0])):
                db.add(Claim(platform="x", verbatim=f"v{i}", claim_type="normatif",
                             embedding=emb, dedup_key=f"k{i}"))
            await db.commit()
            ids = [r for r in (await db.execute(select(Claim.id).order_by(Claim.id))).scalars()]

        index = get_index()
        # L'orthogonal (score 0) tombe sous le seuil.
        assert [i for i, _ in await index.nearest([1.0, 0.0, 0.0], k=5, min_score=0.5)] \
            == [ids[0], ids[1]]
        # Le plus proche est exclu explicitement.
        assert [i for i, _ in await index.nearest(
            [1.0, 0.0, 0.0], k=5, min_score=0.5, exclude_ids={ids[0]})] == [ids[1]]

    try:
        asyncio.run(run())
    finally:
        for c in _CACHES:
            c.cache_clear()
        reset_index()


def test_sqlite_setup_is_a_no_op(tmp_path, monkeypatch):
    """Hors Postgres, préparer l'index ne doit rien exiger ni rien casser."""
    _fresh(tmp_path, monkeypatch, "s.db")

    async def run():
        await init_db()
        index = get_index()
        assert (await index.ensure_ready())["ready"] is True
        assert (await index.sync())["synced"] == 0

    try:
        asyncio.run(run())
    finally:
        for c in _CACHES:
            c.cache_clear()
        reset_index()
