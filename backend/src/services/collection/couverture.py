"""Ce que la base contient de chaque figure depuis 2022, et le rattrapage de ce qui manque.

La campagne 2026-2027 se lit contre ce qui a été dit depuis la présidentielle de
2022 : c'est la profondeur utile, pas 2012. La collecte en direct ne voit que les
derniers tweets de chaque compte ; l'historique vient de Wayback, qui n'en a
archivé qu'une partie. Ce module dit, mois par mois, où sont les trous, et
comble ce qui peut l'être.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone

import structlog
from sqlalchemy import select

from src.database import get_session_factory
from src.models.personality import Personality
from src.models.pipeline_run import PipelineRun, PipelineStep
from src.models.post import Post

logger = structlog.get_logger(__name__)

DEPUIS = datetime(2022, 1, 1, tzinfo=timezone.utc)
FIGURES_CLES = 25


async def couverture(db, *, depuis: datetime = DEPUIS) -> dict:
    """Pour chaque figure active : tweets en base par mois, total annoncé par X, mois vides."""
    figures = (await db.execute(
        select(Personality).where(Personality.is_active.is_(True), Personality.handle.isnot(None))
    )).scalars().all()
    rows = (await db.execute(
        select(Post.personality_id, Post.published_at).where(Post.published_at >= depuis))).all()
    par_fig: dict[int, Counter] = {}
    for pid, d in rows:
        par_fig.setdefault(pid, Counter())[d.strftime("%Y-%m")] += 1
    maintenant = datetime.now(timezone.utc)
    mois = []
    m = depuis.replace(day=1)
    while m <= maintenant:
        mois.append(m.strftime("%Y-%m"))
        m = (m + timedelta(days=32)).replace(day=1)
    out = []
    for f in figures:
        c = par_fig.get(f.id, Counter())
        out.append({
            "id": f.id, "nom": f.full_name, "handle": f.handle, "groupe": f.group_code,
            "abonnes": f.followers_count, "tweets_annonces_par_x": f.statuses_count,
            "en_base_depuis": sum(c.values()), "mois_vides": sum(1 for k in mois if not c.get(k)),
            "par_mois": {k: c.get(k, 0) for k in mois},
        })
    out.sort(key=lambda x: -(x["abonnes"] or 0))
    return {"depuis": depuis.date().isoformat(), "mois": mois, "figures": out}


async def rattrapage_quotidien(*, force: bool = False) -> dict:
    """Comble par Wayback l'historique des figures clés depuis 2022, une fois par jour au plus.

    Les figures clés sont les plus suivies, d'après les profils lus par la
    collecte : le choix vient des données, pas d'une liste écrite à la main.
    Le rattrapage ne demande que les tweets absents de la base, et fxtwitter
    n'est pas à nous : on reste poli et borné.
    """
    from src.services.collection.x_backfill import run_backfill

    factory = get_session_factory()
    async with factory() as db:
        dernier = await db.scalar(
            select(PipelineRun.started_at).join(PipelineStep, PipelineStep.run_id == PipelineRun.id)
            .where(PipelineStep.stage == "rattrapage", PipelineStep.status == "ok",
                   PipelineStep.stats.isnot(None))
            .order_by(PipelineRun.started_at.desc()).limit(1))
        if not force and dernier and datetime.now(timezone.utc) - dernier.replace(
                tzinfo=dernier.tzinfo or timezone.utc) < timedelta(hours=23):
            return {"skipped": "déjà fait dans les dernières 24 heures"}
        cles = (await db.execute(
            select(Personality.handle)
            .where(Personality.is_active.is_(True), Personality.handle.isnot(None),
                   Personality.followers_count.isnot(None))
            .order_by(Personality.followers_count.desc()).limit(FIGURES_CLES))).scalars().all()
    stats = await run_backfill(handles=list(cles), since_year=DEPUIS.year, per_handle=300, max_fetch=1500)
    return {k: v for k, v in stats.items()}
