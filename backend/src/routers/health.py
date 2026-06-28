from datetime import datetime, timezone

from fastapi import APIRouter
from sqlalchemy import func, select

from src.config import get_settings
from src.database import get_session_factory
from src.models.article import Article
from src.models.collection_run import CollectionRun
from src.models.media_source import MediaSource
from src.models.personality import Personality
from src.models.post import Post
from src.vocabulary import Nature, RunKind, RunStatus

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


def _pct(part: int | None, total: int | None) -> float:
    return round(100 * (part or 0) / total, 1) if total else 0.0


@router.get("/health/collection-report")
async def collection_report() -> dict:
    """Porte « prêt pour l'analyse » (C5) — état chiffré de la collecte par canal.

    Agrège couverture / complétude des métadonnées / archivage / fraîcheur. Sert à
    décider OBJECTIVEMENT quand basculer sur l'analyse : on ne raffine que sur un
    substrat dont on connaît la qualité (cf ROADMAP §1)."""
    factory = get_session_factory()
    async with factory() as db:
        # --- X / posts ---
        n_posts = await db.scalar(select(func.count(Post.id))) or 0
        n_eng = await db.scalar(
            select(func.count(Post.id)).where(Post.likes.isnot(None))
        ) or 0
        n_html = await db.scalar(
            select(func.count(Post.id)).where(Post.collected_via == "html")
        ) or 0
        n_post_arch = await db.scalar(
            select(func.count(Post.id)).where(Post.snapshot_url.isnot(None))
        ) or 0
        # --- Presse / articles ---
        n_art = await db.scalar(select(func.count(Article.id))) or 0
        n_full = await db.scalar(
            select(func.count(Article.id)).where(Article.is_full_text.is_(True))
        ) or 0
        n_paywall = await db.scalar(
            select(func.count(Article.id)).where(Article.paywalled.is_(True))
        ) or 0
        n_pdp = await db.scalar(
            select(func.count(Article.id)).where(Article.nature == Nature.PRISE_DE_PAROLE)
        ) or 0
        n_estim = await db.scalar(
            select(func.count(Article.id)).where(Article.published_estimated.is_(True))
        ) or 0
        n_art_arch = await db.scalar(
            select(func.count(Article.id)).where(Article.snapshot_url.isnot(None))
        ) or 0
        # --- Couverture pool & sources ---
        n_pers = await db.scalar(select(func.count(Personality.id))) or 0
        n_handle = await db.scalar(
            select(func.count(Personality.id)).where(
                Personality.is_active.is_(True), Personality.handle.isnot(None)
            )
        ) or 0
        n_collected = await db.scalar(
            select(func.count(Personality.id)).where(
                Personality.last_collected_at.isnot(None)
            )
        ) or 0
        n_src_active = await db.scalar(
            select(func.count(MediaSource.id)).where(MediaSource.is_active.is_(True))
        ) or 0
        n_src_failing = await db.scalar(
            select(func.count(MediaSource.id)).where(
                MediaSource.is_active.is_(True),
                MediaSource.consecutive_failures >= _FAIL_THRESHOLD,
            )
        ) or 0

    return {
        "x": {
            "posts": n_posts,
            "with_engagement": n_eng, "engagement_pct": _pct(n_eng, n_posts),
            "via_html_pct": _pct(n_html, n_posts),
            "archived_pct": _pct(n_post_arch, n_posts),
            "handles_active": n_handle,
            "handles_collected": n_collected,
            "handle_coverage_pct": _pct(n_collected, n_handle),
        },
        "press": {
            "articles": n_art,
            "full_text": n_full, "full_text_pct": _pct(n_full, n_art),
            "paywalled_pct": _pct(n_paywall, n_art),
            "prises_de_parole": n_pdp, "pdp_pct": _pct(n_pdp, n_art),
            "date_estimated_pct": _pct(n_estim, n_art),
            "archived_pct": _pct(n_art_arch, n_art),
            "sources_active": n_src_active,
            "sources_failing": n_src_failing,
        },
        "pool": {"personalities": n_pers, "with_active_handle": n_handle},
    }


# Au-delà de N échecs consécutifs, une source/un handle est « à surveiller »
# (flux cassé, 403 silencieux, mauvais @, instance qui bloque).
_FAIL_THRESHOLD = 2


@router.get("/health/collectors")
async def collectors() -> dict:
    """Sources presse + handles X **muets récurrents** — observabilité fine (C4).

    Complète `/health/freshness` (vue agrégée) par le détail PAR source/handle :
    qui échoue, depuis combien d'échecs, avec quelle erreur. Rend actionnable un
    flux cassé ou un compte mal saisi, au lieu d'un simple compteur global."""
    factory = get_session_factory()
    async with factory() as db:
        sources = list(
            (
                await db.execute(
                    select(MediaSource)
                    .where(
                        MediaSource.is_active.is_(True),
                        MediaSource.consecutive_failures >= _FAIL_THRESHOLD,
                    )
                    .order_by(MediaSource.consecutive_failures.desc())
                )
            ).scalars().all()
        )
        handles = list(
            (
                await db.execute(
                    select(Personality)
                    .where(
                        Personality.is_active.is_(True),
                        Personality.handle.isnot(None),
                        Personality.consecutive_failures >= _FAIL_THRESHOLD,
                    )
                    .order_by(Personality.consecutive_failures.desc())
                )
            ).scalars().all()
        )
        n_active_sources = await db.scalar(
            select(func.count(MediaSource.id)).where(MediaSource.is_active.is_(True))
        )
        n_active_handles = await db.scalar(
            select(func.count(Personality.id)).where(
                Personality.is_active.is_(True), Personality.handle.isnot(None)
            )
        )

    return {
        "fail_threshold": _FAIL_THRESHOLD,
        "press": {
            "active_total": n_active_sources or 0,
            "failing_count": len(sources),
            "failing": [
                {
                    "id": s.id, "name": s.name, "leaning": s.leaning,
                    "last_status": s.last_status,
                    "consecutive_failures": s.consecutive_failures,
                    "last_error": s.last_error,
                    "last_checked_at": s.last_checked_at,
                    "last_collected_at": s.last_collected_at,
                }
                for s in sources
            ],
        },
        "x": {
            "active_total": n_active_handles or 0,
            "failing_count": len(handles),
            "failing": [
                {
                    "id": p.id, "full_name": p.full_name, "handle": p.handle,
                    "last_status": p.last_status,
                    "consecutive_failures": p.consecutive_failures,
                    "last_error": p.last_error,
                    "last_checked_at": p.last_checked_at,
                    "last_collected_at": p.last_collected_at,
                }
                for p in handles
            ],
        },
    }
