"""Passe normative déterministe : désarmée par défaut, mécanique conservée.

Historique : cette passe appariait deux `stance_polarity` opposées dans un même
bloc de référent. Mesuré sur corpus réel (26/08/2026) : **553 arêtes, 553
fausses**. La polarité est produite par le LLM sur une déclaration ISOLÉE —
« voté POUR la censure du budget » et « CONTRE ce budget » sortent opposées
alors que les deux propos s'accordent. Une file de validation inondée de faux
positifs coûte plus cher qu'une file vide : le relecteur cesse de la lire.

La mécanique reste testée (elle sert à l'expérimentation et pourrait revenir si
la polarité devient fiable), mais elle n'alimente plus la file par défaut. Les
paires normatives passent désormais par le juge sémantique, seul capable de
lire un accord de fond derrière des polarités opposées.
"""

import asyncio
from datetime import datetime, timezone

from sqlalchemy import select

from src.config import get_settings
from src.database import get_engine, get_session_factory, init_db
from src.models.claim import Claim
from src.models.contradiction import Contradiction
from src.services.analysis import contradiction_detector as detector
from src.services.analysis.contradiction_detector import run_contradiction_detection

_CACHES = (get_settings, get_engine, get_session_factory)


async def _seed_opposed_stances():
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
        db.add(Claim(verbatim="Pour la double peine, évidemment.", canonical=None,
                     speaker_name="C", party="RN", stance_polarity="pour",
                     dedup_key="k3", **common))
        await db.commit()
    return factory


def _run(tmp_path, monkeypatch, db_name, enabled, check):
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path / db_name}")
    for c in _CACHES:
        c.cache_clear()
    monkeypatch.setattr(detector, "NORMATIVE_ENABLED", enabled)

    async def run():
        factory = await _seed_opposed_stances()
        stats = await run_contradiction_detection()
        async with factory() as db:
            cons = list((await db.execute(select(Contradiction))).scalars().all())
        check(stats, cons)

    try:
        asyncio.run(run())
    finally:
        for c in _CACHES:
            c.cache_clear()


def test_normative_pass_is_disarmed_by_default(tmp_path, monkeypatch):
    """Par défaut, aucune arête normative n'entre dans la file de validation."""
    def check(stats, cons):
        assert stats["normative_new"] == 0
        assert cons == []

    _run(tmp_path, monkeypatch, "off.db", False, check)


def test_normative_mechanics_still_work_when_enabled(tmp_path, monkeypatch):
    """Activée explicitement, la passe apparie toujours les polarités opposées.

    A(pour) ⇄ B(contre) et C(pour) ⇄ B(contre) : deux paires ; jamais A ⇄ C.
    """
    def check(stats, cons):
        assert stats["normative_new"] == 2
        assert len(cons) == 2
        assert all(c.status == "pending" for c in cons)
        assert all(c.detection_method == "deterministe" for c in cons)

    _run(tmp_path, monkeypatch, "on.db", True, check)


def test_default_flag_is_off():
    """Le défaut du module est bien « désarmé » — pas seulement dans les tests."""
    assert detector.NORMATIVE_ENABLED is False
