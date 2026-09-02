"""Le registre des engagements — ce à quoi ils se sont engagés, et depuis quand.

Un engagement est une déclaration : le registre est donc une VUE des propos, pas
une collection parallèle. C'est ce qui garantit qu'un engagement porte la même
source, la même date et le même locuteur vérifié que le reste du corpus.

Ce que l'API ne fait pas : poser un verdict. Les cinq états du Polimètre
existent, aucun n'est attribué par la machine — et pour une opposition qui n'a
jamais gouverné, ils sont tous « en attente ». Le registre vaut par ce qu'il
consigne aujourd'hui pour la confrontation de demain.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database import get_db
from src.models.claim import Claim
from src.services.analysis.claim_sources import resolve_claim_urls
from src.services.analysis.pledges import VERDICTS

router = APIRouter(prefix="/engagements", tags=["engagements"])


@router.get("")
async def list_pledges(
    speaker: str | None = Query(None),
    party: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    base = select(Claim).where(Claim.pledge_status.isnot(None))
    if speaker:
        base = base.where(Claim.speaker_name == speaker)
    if party:
        base = base.where(Claim.party == party)

    total = await db.scalar(
        select(func.count()).select_from(base.subquery())) or 0
    rows = list((await db.execute(
        base.order_by(Claim.published_at.desc().nullslast())
        .limit(limit).offset(offset)
    )).scalars().all())
    urls = await resolve_claim_urls(db, rows)

    # Qui s'engage, et combien de fois : la première question qu'on se pose
    # devant un registre, et celle qui ordonne la page.
    par_locuteur = [
        {"speaker": qui, "party": parti, "n": n}
        for qui, parti, n in (await db.execute(
            select(Claim.speaker_name, Claim.party, func.count())
            .where(Claim.pledge_status.isnot(None), Claim.speaker_name.isnot(None))
            .group_by(Claim.speaker_name, Claim.party)
            .order_by(func.count().desc())
        )).all()
    ]

    return {
        "total": total,
        "verdicts": list(VERDICTS),
        "par_locuteur": par_locuteur,
        "items": [
            {
                "id": c.id, "speaker": c.speaker_name, "party": c.party,
                "published_at": c.published_at, "platform": c.platform,
                "verbatim": c.verbatim, "mesure": c.pledge_measure,
                "status": c.pledge_status, "url": urls.get(c.id),
                "subject_id": c.subject_id,
            }
            for c in rows
        ],
    }
