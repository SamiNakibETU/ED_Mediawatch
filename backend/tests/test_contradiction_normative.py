"""A3 normatif : deux positions opposées sur un même référent → contradiction.

Étend le graphe au-delà du chiffré (« pas que les chiffres »), à coût LLM nul.
"""

import asyncio
from datetime import datetime, timezone

from src.config import get_settings
from src.database import get_engine, get_session_factory, init_db
from src.models.claim import Claim
from src.models.contradiction import Contradiction
from src.services.analysis.contradiction_detector import run_contradiction_detection

_CACHES = (get_settings, get_engine, get_session_factory)


def test_opposite_stances_create_contradiction(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path / 'c.db'}")
    for c in _CACHES:
        c.cache_clear()

    async def run():
        await init_db()
        factory = get_session_factory()
        async with factory() as db:
            common = dict(
                platform="x", referent_key="immigration::double_peine::retablir",
                claim_type="normatif", published_at=datetime.now(timezone.utc),
                qty_value=None, confidence=0.7,
            )
            db.add(Claim(verbatim="Il faut rétablir la double peine.", canonical=None,
                         speaker_name="A", party="RN", stance_polarity="pour",
                         dedup_key="k1", **common))
            db.add(Claim(verbatim="Je suis opposé au rétablissement de la double peine.",
                         canonical=None, speaker_name="B", party="RN",
                         stance_polarity="contre", dedup_key="k2", **common))
            # Un 3e claim 'pour' mais d'un autre locuteur : ne contredit pas A.
            db.add(Claim(verbatim="Pour la double peine, évidemment.", canonical=None,
                         speaker_name="C", party="RN", stance_polarity="pour",
                         dedup_key="k3", **common))
            await db.commit()

        stats = await run_contradiction_detection()
        assert stats["normative_new"] >= 1

        async with factory() as db:
            cons = list((await db.execute(
                __import__("sqlalchemy").select(Contradiction)
            )).scalars().all())
        # A(pour) ⇄ B(contre) et C(pour) ⇄ B(contre) : 2 paires opposées ; pas A⇄C.
        assert len(cons) == 2
        assert all(c.status == "pending" for c in cons)

    try:
        asyncio.run(run())
    finally:
        for c in _CACHES:
            c.cache_clear()
