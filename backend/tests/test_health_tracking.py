"""Santé de collecte par handle (C4) : compteur d'échecs consécutifs.

Un handle muet (instance qui bloque) doit incrémenter `consecutive_failures` ;
une collecte réussie doit le remettre à zéro. C'est ce qui rend un @ cassé visible.
"""

import asyncio

from src.config import get_settings
from src.database import get_engine, get_session_factory, init_db
from src.models.personality import Personality
from src.services.collection.x_collector import _record_handle_health

_CACHES = (get_settings, get_engine, get_session_factory)


def test_handle_health_counter(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path / 'h.db'}")
    for c in _CACHES:
        c.cache_clear()

    async def run():
        await init_db()
        factory = get_session_factory()
        async with factory() as db:
            p = Personality(full_name="Test", handle="t_handle", group_code="RN")
            db.add(p)
            await db.commit()
            await db.refresh(p)
            pid = p.id

        # 2 échecs consécutifs → compteur = 2, statut 'blocked'
        async with factory() as db:
            await _record_handle_health(db, pid, "blocked", "all failed", got_new=False)
        async with factory() as db:
            await _record_handle_health(db, pid, "blocked", "all failed", got_new=False)
            p = await db.get(Personality, pid)
            assert p.consecutive_failures == 2
            assert p.last_status == "blocked"
            assert p.last_collected_at is None

        # une réussite → reset à 0 + last_collected_at posé
        async with factory() as db:
            await _record_handle_health(db, pid, "ok", None, got_new=True)
            p = await db.get(Personality, pid)
            assert p.consecutive_failures == 0
            assert p.last_status == "ok"
            assert p.last_collected_at is not None

    try:
        asyncio.run(run())
    finally:
        for c in _CACHES:
            c.cache_clear()
