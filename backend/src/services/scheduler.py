"""Continuous X collection scheduler (APScheduler).

Polls every active personality's timeline on a fixed interval. The same engine
will later host the press collector + the daily analytical pass (theme
classification, inconsistency detection).
"""

from datetime import datetime, timedelta, timezone

import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from src.config import get_settings
from src.services.archive.archiver import run_archival
from src.services.collection.press_collector import run_press_collection
from src.services.collection.x_collector import run_collection

logger = structlog.get_logger(__name__)


async def _analysis_job() -> None:
    """Passe d'analyse automatique, ÉTAPES GRATUITES uniquement.

    Le corpus doit avancer tout seul (embeddings, sujets, détection) sans jamais
    dépenser sans décision : les étapes payantes (L0, nommage, juge) se lancent
    explicitement via POST /pipeline/run?scope=full.
    """
    from src.pipeline.runner import run_pipeline

    await run_pipeline(scope="free", trigger="scheduled")


async def _archive_press_job() -> None:
    await run_archival(kind="press", limit=get_settings().archive_batch_limit)


async def _archive_x_job() -> None:
    await run_archival(kind="x", limit=get_settings().archive_batch_limit)


def _offset(*, minutes: int):
    """Premier tir décalé : ne pas lancer toutes les passes en même temps."""
    from datetime import datetime, timedelta, timezone

    return datetime.now(timezone.utc) + timedelta(minutes=minutes)


def create_scheduler() -> AsyncIOScheduler:
    settings = get_settings()
    hours = settings.collection_interval_hours
    scheduler = AsyncIOScheduler(timezone="UTC")
    scheduler.add_job(
        run_collection,
        trigger=IntervalTrigger(hours=hours),
        id="x_collection",
        name="Continuous X collection",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    # La presse est aussi collectée en continu (prises de parole ED relayées).
    scheduler.add_job(
        run_press_collection,
        trigger=IntervalTrigger(hours=hours),
        id="press_collection",
        name="Continuous press collection",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )

    # Analyse : décalée de 40 min après la collecte, pour travailler sur ce qui
    # vient d'arriver. Étapes GRATUITES seulement — le corpus avance seul
    # (embeddings, sujets, détection) sans jamais dépenser sans décision.
    scheduler.add_job(
        _analysis_job,
        trigger=IntervalTrigger(hours=hours, start_date=_offset(minutes=40)),
        id="analysis",
        name="Passe d'analyse (étapes gratuites)",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )

    # Archivage / reçus (C3) — « ne plus rien perdre ». Décalé de la collecte
    # (premier tir à +20/+25 min) pour archiver ce qui vient d'être collecté,
    # sans tout faire tourner en même temps. Résumable (n'archive que archived_at
    # IS NULL), rate-limité (Wayback lent).
    if settings.archive_backend != "none":
        ah = settings.archive_interval_hours
        now = datetime.now(timezone.utc)
        scheduler.add_job(
            _archive_press_job,
            trigger=IntervalTrigger(hours=ah, start_date=now + timedelta(minutes=20)),
            id="archive_press", name="Press archival (receipts)",
            replace_existing=True, max_instances=1, coalesce=True,
        )
        scheduler.add_job(
            _archive_x_job,
            trigger=IntervalTrigger(hours=ah, start_date=now + timedelta(minutes=25)),
            id="archive_x", name="X archival (receipts)",
            replace_existing=True, max_instances=1, coalesce=True,
        )
        logger.info("scheduler.configured", interval_hours=hours,
                    archive_interval_hours=ah, jobs=["x", "press", "archive_press", "archive_x"])
    else:
        logger.info("scheduler.configured", interval_hours=hours, jobs=["x", "press"])
    return scheduler
