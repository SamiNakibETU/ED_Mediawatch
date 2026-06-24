"""Continuous X collection scheduler (APScheduler).

Polls every active personality's timeline on a fixed interval. The same engine
will later host the press collector + the daily analytical pass (theme
classification, inconsistency detection).
"""

import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from src.config import get_settings
from src.services.collection.press_collector import run_press_collection
from src.services.collection.x_collector import run_collection

logger = structlog.get_logger(__name__)


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
    logger.info("scheduler.configured", interval_hours=hours, jobs=["x", "press"])
    return scheduler
