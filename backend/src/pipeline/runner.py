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

import time
from datetime import datetime, timezone

import structlog
from sqlalchemy import func, select

from src.database import get_session_factory
from src.models.pipeline_run import PipelineRun, PipelineStep
from src.pipeline.stages import FREE, PAID, Stage, resolve_order

logger = structlog.get_logger(__name__)


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
    from src.services.analysis.llm_usage import BudgetExceeded

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
        run = PipelineRun(trigger=trigger, scope=scope)
        db.add(run)
        await db.commit()
        await db.refresh(run)
        run_id = run.id

    cost_before = await _spent_today() if scope != "free" else 0.0
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

    factory = get_session_factory()
    async with factory() as db:
        async def count(model, *where):
            return await db.scalar(select(func.count()).select_from(model).where(*where)) or 0

        posts = await count(Post)
        truncated = await count(Post, Post.text_truncated.is_(True))
        articles = await count(Article)
        claims = await count(Claim)
        embedded = await count(Claim, Claim.embedding.isnot(None))
        in_subject = await count(Claim, Claim.subject_id.isnot(None))
        subjects = await count(Subject)
        labelled = await count(Subject, Subject.status == "labelled")
        confrontable = await count(Subject, Subject.n_speakers >= 2)
        pending = await count(Contradiction, Contradiction.status == "pending")
        confirmed = await count(Contradiction, Contradiction.status == "confirmed")

        last = (await db.execute(
            select(PipelineRun).order_by(PipelineRun.started_at.desc()).limit(1)
        )).scalar_one_or_none()

    steps = [
        {"step": "Publications collectées", "n": posts + articles,
         "detail": f"{posts} posts X · {articles} articles",
         "blocked": f"{truncated} tweets encore tronqués" if truncated else None},
        {"step": "Déclarations extraites", "n": claims,
         "detail": "segmentation L0",
         "blocked": "extraction L0 jamais lancée" if not claims else None},
        {"step": "Déclarations vectorisées", "n": embedded,
         "detail": f"{claims - embedded} sans vecteur" if claims else "",
         "blocked": "embeddings manquants — sujets impossibles"
                    if claims and embedded < claims else None},
        {"step": "Sujets constitués", "n": subjects,
         "detail": f"{labelled} nommés · {confrontable} à ≥2 locuteurs",
         "blocked": "aucun sujet — rien à confronter" if not subjects else None},
        {"step": "Déclarations rattachées à un sujet", "n": in_subject,
         "detail": f"{embedded - in_subject} isolées" if embedded else "",
         "blocked": None},
        {"step": "Rapprochements à relire", "n": pending,
         "detail": f"{confirmed} confirmés par un humain",
         "blocked": "aucun sujet confrontable" if not confrontable else None},
    ]

    return {
        "steps": steps,
        "last_run": {
            "id": last.id, "status": last.status, "scope": last.scope,
            "started_at": last.started_at, "finished_at": last.finished_at,
            "cost_usd": last.cost_usd,
        } if last else None,
    }
