"""Exécution du pipeline : ordonnée, reprenable, tracée.

Garanties tenues ici, et c'est ce qui distingue un système d'une pile de scripts :

* **Ordre** — les dépendances décident, plus la mémoire de l'opérateur.
* **Reprise** — chaque étape est idempotente ; un run interrompu se relance
  sans rien perdre ni dupliquer.
* **Isolation** — une étape qui échoue n'arrête que ce qui en dépend. Le reste
  continue, et l'échec est écrit noir sur blanc.
* **Budget** — un dépassement arrête proprement les étapes payantes et laisse
  passer les gratuites ; on ne perd pas une passe entière pour 3 centimes.
* **Trace** — chaque exécution laisse un enregistrement lisible : quoi, combien
  de temps, ce qui a été produit, ce qui a bloqué.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from datetime import datetime, timedelta, timezone

import structlog
from sqlalchemy import func, select, update

from src.database import get_session_factory
from src.models.pipeline_run import PipelineRun, PipelineStep
from src.pipeline.stages import FREE, PAID, Stage, resolve_order

logger = structlog.get_logger(__name__)

# Le processus signe sa présence à ce rythme ; on le déclare mort après cinq
# battements manqués. Volontairement tolérant : un battement raté à cause d'une
# base momentanément indisponible ne doit pas faire passer un run vivant pour
# un cadavre.
HEARTBEAT_S = 60
STALE_AFTER_S = 5 * HEARTBEAT_S


def _aware(dt: datetime | None) -> datetime | None:
    """SQLite rend des datetimes naïfs là où Postgres les rend datés.

    Comparer les deux lève un TypeError — au pire endroit possible, dans le
    code qui sert justement à dire ce qui va mal.
    """
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


async def _beat(run_id: int) -> None:
    """Rafraîchit le signe de vie tant que ce processus tourne.

    Tâche de fond plutôt qu'un battement entre deux étapes : une collecte peut
    dormir un quart d'heure en attendant le quota X, et une étape longue reste
    une étape vivante.
    """
    factory = get_session_factory()
    while True:
        await asyncio.sleep(HEARTBEAT_S)
        try:
            async with factory() as db:
                await db.execute(
                    update(PipelineRun)
                    .where(PipelineRun.id == run_id)
                    .values(heartbeat_at=datetime.now(timezone.utc))
                )
                await db.commit()
        except Exception:  # noqa: BLE001 — un battement manqué n'arrête rien
            logger.debug("pipeline.heartbeat_failed", run_id=run_id)


async def reap_stale_runs() -> int:
    """Clôt les runs dont le processus a disparu.

    Le cas concret : `railway ssh "… pipeline --full"` attache l'exécution au
    terminal. La collecte X dort en attendant la remise à zéro du quota, la
    session SSH est coupée faute de trafic, le processus meurt avec elle — et
    le run reste « en cours » pour toujours. L'écran affirmait alors qu'un
    travail avançait alors que rien ne tournait, ce qui est pire que pas
    d'information du tout.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=STALE_AFTER_S)
    factory = get_session_factory()
    async with factory() as db:
        running = list((await db.execute(
            select(PipelineRun).where(PipelineRun.status == "running")
        )).scalars().all())

        reaped = 0
        for run in running:
            last = _aware(run.heartbeat_at) or _aware(run.started_at)
            if last is not None and last >= cutoff:
                continue                      # bat encore : bien vivant
            run.status = "interrupted"
            run.finished_at = _aware(run.heartbeat_at) or datetime.now(timezone.utc)
            reaped += 1
        if reaped:
            await db.commit()
            logger.info("pipeline.reaped_stale", runs=reaped)
    return reaped


async def _spent_today() -> float:
    """Dépense LLM du jour, pour imputer un coût au run."""
    from src.services.analysis.llm_usage import get_llm_budget
    try:
        return float((await get_llm_budget().summary())["day_usd"])
    except Exception:  # noqa: BLE001 — la trace ne doit jamais casser le run
        return 0.0


async def run_pipeline(
    *,
    stages: list[str] | None = None,
    scope: str = "free",
    trigger: str = "manual",
    only: bool = False,
) -> dict:
    """Exécute le pipeline et renvoie le rapport.

    `only=True` n'exécute que les étapes nommées, sans leurs dépendances.
    `scope="free"` n'exécute aucune étape payante — c'est le mode par défaut,
    et celui du scheduler : une passe automatique ne doit jamais dépenser sans
    qu'on l'ait décidé.
    """
    # Clore d'abord les runs dont le processus a disparu : sans ça l'écran
    # empile des « en cours » qui ne courent plus.
    await reap_stale_runs()

    # `only` : exécuter EXACTEMENT les étapes nommées, sans tirer leurs
    # dépendances. Utile quand on sait qu'elles viennent de tourner — demander
    # l'extraction relance sinon une heure de collecte cadencée par le quota X.
    # À manier en connaissance de cause : les dépendances existent pour garantir
    # qu'une étape travaille sur des données à jour.
    ordered = resolve_order(stages)
    if only and stages:
        wanted = set(stages)
        ordered = [s for s in ordered if s.name in wanted]
    if scope == "free":
        ordered = [s for s in ordered if s.cost == FREE]

    factory = get_session_factory()
    async with factory() as db:
        run = PipelineRun(trigger=trigger, scope=scope,
                          heartbeat_at=datetime.now(timezone.utc))
        db.add(run)
        await db.commit()
        await db.refresh(run)
        run_id = run.id

    cost_before = await _spent_today() if scope != "free" else 0.0

    beat = asyncio.create_task(_beat(run_id))
    try:
        report, failed, budget_hit = await _run_stages(ordered, run_id)
    finally:
        beat.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await beat

    cost = max(0.0, (await _spent_today()) - cost_before) if scope != "free" else 0.0
    overall = ("failed" if failed
               else "budget_exceeded" if budget_hit
               else "ok")

    async with factory() as db:
        run = await db.get(PipelineRun, run_id)
        if run is not None:
            run.finished_at = datetime.now(timezone.utc)
            run.status = overall
            run.cost_usd = round(cost, 4)
            await db.commit()

    logger.info("pipeline.done", run_id=run_id, status=overall,
                stages=len(report), cost_usd=round(cost, 4))
    return {"run_id": run_id, "status": overall, "scope": scope,
            "cost_usd": round(cost, 4), "steps": report}


async def _run_stages(ordered: list[Stage], run_id: int) -> tuple[list[dict], set[str], bool]:
    """Déroule les étapes ; renvoie (rapport, étapes en échec, budget atteint).

    Extraite de `run_pipeline` pour que le battement de cœur puisse l'encadrer
    dans un `try/finally` : quoi qu'il arrive ici, la tâche de fond s'arrête.
    """
    from src.services.analysis.llm_usage import BudgetExceeded

    factory = get_session_factory()
    failed: set[str] = set()
    budget_hit = False
    report: list[dict] = []

    for stage in ordered:
        blocked = [d for d in stage.depends_on if d in failed]
        if blocked:
            outcome = ("skipped", 0.0, None,
                       f"dépend de {', '.join(blocked)} qui n'a pas abouti")
            failed.add(stage.name)
        elif budget_hit and stage.cost == PAID:
            outcome = ("skipped", 0.0, None, "budget LLM atteint plus tôt dans ce run")
        else:
            t0 = time.monotonic()
            try:
                stats = await stage.run()
                outcome = ("ok", time.monotonic() - t0, stats, None)
            except BudgetExceeded as exc:
                # Pas un échec : la protection a fonctionné. Les étapes
                # gratuites suivantes doivent continuer.
                budget_hit = True
                outcome = ("budget_exceeded", time.monotonic() - t0, None, str(exc)[:300])
            except Exception as exc:  # noqa: BLE001
                failed.add(stage.name)
                outcome = ("failed", time.monotonic() - t0, None,
                           f"{type(exc).__name__}: {str(exc)[:300]}")
                logger.warning("pipeline.stage_failed", stage=stage.name,
                               error=str(exc)[:200])

        status, duration, stats, detail = outcome
        async with factory() as db:
            db.add(PipelineStep(
                run_id=run_id, stage=stage.name, status=status,
                duration_s=round(duration, 2), stats=stats, detail=detail,
            ))
            await db.commit()
        report.append({"stage": stage.name, "label": stage.label, "cost": stage.cost,
                       "status": status, "duration_s": round(duration, 1),
                       "stats": stats, "detail": detail})
        logger.info("pipeline.stage", stage=stage.name, status=status,
                    duration_s=round(duration, 1))

    return report, failed, budget_hit


async def funnel() -> dict:
    """L'entonnoir : combien d'items à chaque étage, et où ça s'arrête.

    C'est la réponse à « pourquoi il n'y a rien à l'écran ». Chaque ligne dit
    ce qui existe et ce qui manque pour passer à l'étage suivant.
    """
    from src.models.article import Article
    from src.models.claim import Claim
    from src.models.contradiction import Contradiction
    from src.models.post import Post
    from src.models.subject import Subject

    # Un run mort ne doit jamais s'afficher « en cours » : c'est précisément
    # sur cet écran qu'on vient chercher la vérité.
    await reap_stale_runs()

    factory = get_session_factory()
    async with factory() as db:
        async def count(model, *where):
            return await db.scalar(select(func.count()).select_from(model).where(*where)) or 0

        posts = await count(Post)
        truncated = await count(Post, Post.text_truncated.is_(True))
        articles = await count(Article)
        claims = await count(Claim)
        # Un propos sans locuteur ne se compare pas : c'est la métrique qui dit
        # si le corpus sert à quelque chose, pas le nombre brut de déclarations.
        attributed = await count(Claim, Claim.speaker_name.isnot(None))
        embedded = await count(Claim, Claim.embedding.isnot(None))
        in_subject = await count(Claim, Claim.subject_id.isnot(None))
        subjects = await count(Subject)
        labelled = await count(Subject, Subject.status == "labelled")
        confrontable = await count(Subject, Subject.n_speakers >= 2)
        pending = await count(Contradiction, Contradiction.status == "pending")
        confirmed = await count(Contradiction, Contradiction.status == "confirmed")

        # Le reliquat de segmentation : c'est lui qui dit si l'extraction est
        # « finie » ou seulement « en cours ». Sans ce chiffre, un compteur qui
        # ne bouge plus est indistinguable d'une panne.
        to_segment = await count(
            Post, Post.l0_done_at.is_(None), Post.is_retweet.is_(False),
            Post.text_truncated.isnot(True),
        ) + await count(Article, Article.l0_done_at.is_(None))

        # Codage thématique : un propos non codé sort des agrégations par
        # topique, donc de la mesure d'attention et de la revue.
        from src.services.analysis.cap import CAP_VERSION
        coded = await count(Claim, Claim.cap_version.startswith(CAP_VERSION))
        on_topic = await count(
            Claim, Claim.cap_version.startswith(CAP_VERSION), Claim.cap_major.isnot(None))

        last = (await db.execute(
            select(PipelineRun).order_by(PipelineRun.started_at.desc()).limit(1)
        )).scalar_one_or_none()

    # Chaque étage porte une CLÉ stable. Le front lisait l'entonnoir par
    # position : insérer un étage décalait tout et affichait un chiffre pour un
    # autre, sans erreur ni signal.
    #
    # `blocked` dit ce qui manque ; `todo` dit ce qui va s'en occuper. Depuis que
    # la passe complète tourne toute seule, la réponse est presque toujours « la
    # prochaine passe » — et c'est précisément ce qu'il faut afficher plutôt que
    # de laisser croire qu'une intervention est attendue.
    steps = [
        {"key": "collecte", "step": "Publications collectées", "n": posts + articles,
         "detail": f"{posts} posts X · {articles} articles",
         "blocked": f"{truncated} tweets encore tronqués" if truncated else None,
         "todo": ("la réparation en reprend 600 par passe ; L0 les laisse de côté "
                  "d'ici là, segmenter un texte coupé à 280 produit des "
                  "déclarations fausses par omission") if truncated else None},
        {"key": "extraction", "step": "Déclarations extraites", "n": claims,
         "detail": (f"{attributed} attribuées à un locuteur"
                    + (f" · {to_segment} sources restent à segmenter" if to_segment
                       else " · tout le corpus est segmenté")),
         "blocked": ("aucune déclaration extraite" if not claims
                     else f"{claims - attributed} propos sans locuteur — non comparables"
                          if claims - attributed else None),
         "todo": (f"la passe complète en traite ~1900 par cycle de 4 h"
                  if to_segment else None)},
        {"key": "codage", "step": "Propos situés dans la grille", "n": coded,
         "detail": (f"{on_topic} rattachés à un domaine d'action publique"
                    + (f" · {coded - on_topic} hors politique publique"
                       if coded - on_topic else "")),
         "blocked": (f"{claims - coded} propos pas encore codés"
                     if claims - coded else None),
         "todo": ("le codage tourne à chaque passe, au tier 1"
                  if claims - coded else None)},
        {"key": "vectorisation", "step": "Déclarations vectorisées", "n": embedded,
         "detail": f"{claims - embedded} sans vecteur" if claims else "",
         "blocked": "embeddings manquants — sujets impossibles"
                    if claims and embedded < claims else None,
         "todo": "étape gratuite : la prochaine passe les vectorise"
                 if claims and embedded < claims else None},
        {"key": "sujets", "step": "Sujets constitués", "n": subjects,
         "detail": f"{labelled} nommés · {confrontable} à ≥2 locuteurs",
         "blocked": "aucun sujet — rien à confronter" if not subjects else None,
         "todo": "le regroupement a besoin de déclarations vectorisées"
                 if not subjects else None},
        {"key": "rattachement", "step": "Déclarations rattachées à un sujet", "n": in_subject,
         "detail": f"{embedded - in_subject} isolées" if embedded else "",
         "blocked": None, "todo": None},
        {"key": "relecture", "step": "Rapprochements à relire", "n": pending,
         "detail": f"{confirmed} confirmés par un humain",
         "blocked": "aucun sujet confrontable" if not confrontable else None,
         "todo": ("un sujet ne devient confrontable qu'à partir de deux "
                  "locuteurs sur le même objet de débat")
                 if not confrontable else None},
    ]

    return {
        "steps": steps,
        "last_run": {
            "id": last.id, "status": last.status, "scope": last.scope,
            "started_at": last.started_at, "finished_at": last.finished_at,
            "cost_usd": last.cost_usd,
            "stages": [
                {"stage": s.stage, "status": s.status, "detail": s.detail}
                for s in last.steps
            ],
            # Dire ce que le statut implique, plutôt que laisser interpréter.
            "note": {
                "running": "une passe est en cours — les compteurs vont bouger",
                "interrupted": "le processus a disparu (terminal fermé ?) — "
                               "relancer via POST /pipeline/run, qui tourne détaché",
                "budget_exceeded": "plafond LLM atteint : les étapes payantes "
                                   "se sont arrêtées proprement",
                "failed": "au moins une étape a échoué — voir le détail",
            }.get(last.status),
        } if last else None,
    }
