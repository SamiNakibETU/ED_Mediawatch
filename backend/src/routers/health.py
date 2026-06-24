from datetime import datetime, timezone

from fastapi import APIRouter
from sqlalchemy import func, select

from src.config import get_settings
from src.database import get_session_factory
from src.models.collection_run import CollectionRun
from src.models.media_source import MediaSource
from src.models.personality import Personality
from src.models.post import Post
from src.vocabulary import RunKind, RunStatus

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict:
    factory = get_session_factory()
    async with factory() as db:
        n_personalities = await db.scalar(select(func.count(Personality.id)))
        n_active = await db.scalar(
            select(func.count(Personality.id)).where(
                Personality.is_active.is_(True), Personality.handle.isnot(None)
            )
        )
        n_posts = await db.scalar(select(func.count(Post.id)))
    return {
        "status": "ok",
        "personalities": n_personalities or 0,
        "active_with_handle": n_active or 0,
        "posts": n_posts or 0,
    }


def _age_hours(dt: datetime | None, now: datetime) -> float | None:
    if dt is None:
        return None
    if dt.tzinfo is None:  # tolère un datetime naïf relu (ne devrait pas arriver)
        dt = dt.replace(tzinfo=timezone.utc)
    return round((now - dt).total_seconds() / 3600, 1)


async def _last_completed(db, kind: str) -> datetime | None:
    return await db.scalar(
        select(func.max(CollectionRun.completed_at)).where(
            CollectionRun.kind == kind, CollectionRun.status == RunStatus.COMPLETED
        )
    )


@router.get("/health/freshness")
async def freshness() -> dict:
    """Fraîcheur de collecte par source — rend visible une collecte muette.

    Une source/passe est `stale` si elle n'a rien renvoyé depuis
    `freshness_alert_hours`. Signale aussi les runs « zombies » (running sans
    completed_at au-delà du seuil) : un process tombé en pleine collecte.
    """
    settings = get_settings()
    threshold = settings.freshness_alert_hours
    now = datetime.now(timezone.utc)
    factory = get_session_factory()

    def _stale(age: float | None) -> bool:
        return age is None or age > threshold

    async with factory() as db:
        # --- Presse : par source (last_collected_at = dernier article retenu) ---
        sources = list(
            (
                await db.execute(
                    select(MediaSource).where(MediaSource.is_active.is_(True))
                )
            ).scalars().all()
        )
        press_sources = sorted(
            (
                {
                    "id": s.id,
                    "name": s.name,
                    "leaning": s.leaning,
                    "last_collected_at": s.last_collected_at,
                    "age_hours": _age_hours(s.last_collected_at, now),
                    "stale": _stale(_age_hours(s.last_collected_at, now)),
                }
                for s in sources
            ),
            key=lambda d: (d["age_hours"] is None, d["age_hours"] or 0),
            reverse=True,
        )

        # --- X : dernier post collecté (created_at = horodatage côté collecte) ---
        x_last_post = await db.scalar(select(func.max(Post.created_at)))

        x_last_run = await _last_completed(db, RunKind.X)
        press_last_run = await _last_completed(db, RunKind.PRESS)

        # Runs « zombies » : status=running mais lancés il y a plus que le seuil
        # (process tombé en pleine collecte). On les remonte, sans muter (GET).
        running = list(
            (
                await db.execute(
                    select(CollectionRun.id, CollectionRun.kind, CollectionRun.started_at)
                    .where(CollectionRun.status == RunStatus.RUNNING)
                    .order_by(CollectionRun.started_at.desc())
                )
            ).all()
        )
    zombies = [
        {"id": rid, "kind": kind, "started_at": started, "age_hours": _age_hours(started, now)}
        for rid, kind, started in running
        if _stale(_age_hours(started, now))
    ]

    x_age = _age_hours(x_last_run, now)
    press_stale_sources = [s for s in press_sources if s["stale"]]
    return {
        "now": now,
        "threshold_hours": threshold,
        "x": {
            "last_run_completed_at": x_last_run,
            "age_hours": x_age,
            "stale": _stale(x_age),
            "last_post_at": x_last_post,
        },
        "press": {
            "last_run_completed_at": press_last_run,
            "age_hours": _age_hours(press_last_run, now),
            "stale": _stale(_age_hours(press_last_run, now)),
            "sources_total": len(press_sources),
            "sources_stale": len(press_stale_sources),
            "sources": press_sources,
        },
        "zombie_runs": zombies,
    }
