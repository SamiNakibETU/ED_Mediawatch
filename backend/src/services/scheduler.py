"""Cadencement : le système travaille seul.

Une seule passe périodique — le pipeline complet, du graphe. Elle collecte,
enrichit, extrait, regroupe, juge, dans l'ordre que les dépendances imposent,
et s'arrête proprement au plafond de dépense. Plus un faucheur qui clôt les
passes dont le processus a disparu, et l'archivage des reçus.

Ce qu'il ne faut PAS réintroduire ici : un job qui refait une étape du
pipeline. Il y en avait deux (collecte X, collecte presse) et ils doublaient la
consommation du quota X à chaque cycle.
"""

from datetime import datetime, timedelta, timezone

import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from src.config import get_settings
from src.services.archive.archiver import run_archival

logger = structlog.get_logger(__name__)


def auto_scope() -> str:
    """Périmètre de la passe automatique — et pourquoi il peut être « full ».

    Le corpus doit avancer seul : collecter sans jamais extraire ne produit
    qu'un tas de posts. Les étapes payantes en font donc partie.

    Ce qui rend l'autonomie acceptable, ce n'est pas la prudence de l'opérateur,
    c'est le plafond : la dépense est comptée sur les tokens réellement
    consommés, et `BudgetExceeded` arrête proprement les étapes payantes en
    laissant les gratuites finir. Sans plafond armé, cette garantie n'existe
    plus — on retombe alors sur « free » plutôt que de laisser une boucle
    automatique dépenser sans borne.
    """
    s = get_settings()
    if s.pipeline_auto_scope != "full":
        return "free"
    if s.llm_daily_budget_usd <= 0 and s.llm_monthly_budget_usd <= 0:
        logger.warning("scheduler.auto_scope_downgraded",
                       reason="aucun plafond LLM armé")
        return "free"
    return "full"


async def _analysis_job() -> None:
    """L'analyse seule, sur ce qui est déjà en base.

    Séparée de la collecte, et c'est ce qui la rend utile. Enchaînée derrière
    elle, elle n'arrivait jamais : `collect_x` dure 2 h 20 au rythme du quota X,
    et toute passe redémarrée repart de la collecte. Résultat mesuré en
    production : 33 000 publications collectées, 8 400 déclarations extraites,
    et zéro sujet — la chaîne n'avait jamais dépassé son premier étage.

    Toutes les étapes sont idempotentes et reprennent où elles se sont
    arrêtées : une passe interrompue n'est pas perdue, la suivante continue.
    """
    from src.pipeline.runner import run_pipeline
    from src.pipeline.stages import analysis_stages

    await run_pipeline(stages=analysis_stages(), only=True,
                       scope=auto_scope(), trigger="scheduled")


async def _collection_job() -> None:
    """La collecte seule : lente, bornée par le quota, sans rien derrière."""
    from src.pipeline.runner import run_pipeline
    from src.pipeline.stages import COLLECTE

    await run_pipeline(stages=list(COLLECTE), only=True,
                       scope="free", trigger="scheduled")


async def _reap_job() -> None:
    from src.pipeline.runner import reap_stale_runs

    await reap_stale_runs()


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
    scope = auto_scope()
    scheduler = AsyncIOScheduler(timezone="UTC")

    # UN SEUL moteur : la passe de pipeline. Elle commence par la collecte X et
    # presse, puis enchaîne dans l'ordre déclaré par le graphe.
    #
    # Il y avait ici, en plus, deux jobs `x_collection` et `press_collection`
    # qui refaisaient ce que le pipeline fait déjà : deux collectes par cycle
    # sur le même quota X, d'où les attentes de quota à répétition. Le graphe
    # est l'autorité sur l'ordre ; des jobs parallèles qui doublent ses étapes
    # annulent exactement ce qu'il apporte.
    #
    # `max_instances=1` compte ici plus qu'ailleurs : une passe complète peut
    # dépasser l'intervalle, et deux extractions concurrentes paieraient deux
    # fois le même texte. `coalesce` : on rattrape une seule fois, pas dix.
    scheduler.add_job(
        _collection_job,
        trigger=IntervalTrigger(hours=hours, start_date=_offset(minutes=2)),
        id="collection",
        name="Collecte (X et presse)",
        replace_existing=True, max_instances=1, coalesce=True,
    )

    # L'analyse tourne PLUS SOUVENT que la collecte, et indépendamment d'elle :
    # elle travaille sur ce qui est déjà en base, chaque étape par lots bornés.
    # Une heure suffit à rattraper un arriéré en quelques passes ; l'attacher au
    # cycle de quatre heures de la collecte le ferait durer quatre fois plus.
    scheduler.add_job(
        _analysis_job,
        trigger=IntervalTrigger(hours=1, start_date=_offset(minutes=4)),
        id="analysis",
        name=f"Analyse ({'avec étapes payantes' if scope == 'full' else 'gratuite'})",
        replace_existing=True, max_instances=1, coalesce=True,
    )

    # Faucheur : un run dont le processus a disparu (terminal SSH fermé pendant
    # une attente de quota) resterait « en cours » pour toujours, et l'écran
    # affirmerait qu'un travail avance alors que rien ne tourne.
    scheduler.add_job(
        _reap_job,
        trigger=IntervalTrigger(minutes=10, start_date=_offset(minutes=5)),
        id="reap_stale_runs",
        name="Clôture des passes interrompues",
        replace_existing=True, max_instances=1, coalesce=True,
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
        logger.info("scheduler.configured", interval_hours=hours, auto_scope=scope,
                    archive_interval_hours=ah,
                    jobs=["collection", "analysis", "reap", "archive_press", "archive_x"])
    else:
        logger.info("scheduler.configured", interval_hours=hours, auto_scope=scope,
                    jobs=["collection", "analysis", "reap"])
    return scheduler
