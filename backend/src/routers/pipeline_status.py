"""État et pilotage du pipeline.

`/pipeline/funnel` est la première chose à regarder quand « il n'y a rien à
l'écran » : il dit à quel étage le corpus s'arrête et pourquoi.
"""

from fastapi import APIRouter, BackgroundTasks, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database import get_db
from src.security import require_token
from src.models.pipeline_run import PipelineRun
from src.pipeline.runner import funnel, run_pipeline
from src.pipeline.stages import STAGES

router = APIRouter(prefix="/pipeline", tags=["pipeline"])


@router.get("/funnel")
async def pipeline_funnel() -> dict:
    return await funnel()


@router.get("/stages")
async def list_stages() -> dict:
    """Le graphe, tel qu'il est réellement exécuté."""
    return {
        "stages": [
            {"name": s.name, "label": s.label, "cost": s.cost,
             "depends_on": list(s.depends_on), "produces": s.produces}
            for s in STAGES
        ]
    }


@router.get("/runs")
async def recent_runs(
    limit: int = Query(10, ge=1, le=50), db: AsyncSession = Depends(get_db)
) -> dict:
    runs = list(
        (
            await db.execute(
                select(PipelineRun).order_by(PipelineRun.started_at.desc()).limit(limit)
            )
        ).scalars().all()
    )
    return {
        "items": [
            {
                "id": r.id, "status": r.status, "scope": r.scope,
                "trigger": r.trigger, "started_at": r.started_at,
                "finished_at": r.finished_at, "cost_usd": r.cost_usd,
                "steps": [
                    {"stage": s.stage, "status": s.status,
                     "duration_s": s.duration_s, "stats": s.stats, "detail": s.detail}
                    for s in r.steps
                ],
            }
            for r in runs
        ]
    }


@router.post("/run", dependencies=[Depends(require_token)])
async def trigger_run(
    background: BackgroundTasks,
    scope: str = Query("free", pattern="^(free|full)$"),
    stage: list[str] | None = Query(None, description="Étapes ciblées (dépendances incluses)"),
) -> dict:
    """Lance une passe en tâche de fond.

    `scope=free` (défaut) n'exécute aucune étape payante : déclencher le
    pipeline ne doit jamais dépenser par accident.
    """
    background.add_task(run_pipeline, stages=stage, scope=scope, trigger="manual")
    return {"queued": True, "scope": scope, "stages": stage or "toutes"}
