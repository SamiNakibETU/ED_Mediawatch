"""Les déclarations qui comptent — ce que la une lit.

Le classement vient de `relevance.py` ; chaque ligne porte son pourquoi en
clair. La page ne montre pas « les plus récentes » — un observatoire du propos
dans la durée qui trierait par date redeviendrait un fil — ni « les plus
aimées » — les likes bruts classent un militant devant la cheffe du parti. Elle
montre ce qui est inhabituel, repris, contredit ou engageant, et dit lequel.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database import get_db
from src.models.claim import Claim
from src.models.personality import Personality
from src.models.subject import Subject
from src.services.analysis.cap import CAP_VERSION
from src.services.analysis.claim_sources import resolve_claim_urls

# Une une n'est pas le fil d'une personne. Au-delà de deux lignes, le troisième
# propos du même locuteur cède la place au premier d'un autre — même mieux
# classé. C'est une règle de rédaction, pas de score.
MAX_PAR_LOCUTEUR = 2

router = APIRouter(prefix="/declarations", tags=["declarations"])


@router.get("")
async def list_declarations(
    jours: int = Query(7, ge=1, le=365, description="Fenêtre récente"),
    limit: int = Query(12, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
) -> dict:
    depuis = datetime.now(timezone.utc) - timedelta(days=jours)
    rows = list((await db.execute(
        select(Claim, Personality.handle, Personality.photo_url, Subject.label,
               Subject.status)
        .outerjoin(Personality, Personality.id == Claim.personality_id)
        .outerjoin(Subject, Subject.id == Claim.subject_id)
        .where(Claim.published_at >= depuis,
               Claim.speaker_name.isnot(None),   # sans auteur, rien à imputer
               Claim.relevance.isnot(None),
               # Codé hors politique publique : jamais en une, quelle que soit
               # l'audience. Pas encore codé : on ne sait pas, on laisse passer.
               ~(Claim.cap_version.startswith(CAP_VERSION) & Claim.cap_major.is_(None)))
        .order_by(Claim.relevance.desc())
        # Une source produit plusieurs déclarations, qui partagent son audience
        # et donc son score : sans dédoublonnage la une affichait quatre
        # fragments du même tweet en tête. Une ligne par source, la mieux
        # classée ; on lit large puis on garde `limit`.
        .limit(limit * 6)
    )).all())
    vues: set[tuple] = set()
    par_locuteur: dict[str, int] = {}
    gardes = []
    for row in rows:
        c = row[0]
        cle = ("post", c.post_id) if c.post_id else ("article", c.article_id)
        if cle in vues or par_locuteur.get(c.speaker_name, 0) >= MAX_PAR_LOCUTEUR:
            continue
        vues.add(cle)
        par_locuteur[c.speaker_name] = par_locuteur.get(c.speaker_name, 0) + 1
        gardes.append(row)
        if len(gardes) >= limit:
            break
    rows = gardes
    urls = await resolve_claim_urls(db, [r[0] for r in rows])

    return {
        "jours": jours,
        "items": [
            {
                "id": c.id, "speaker": c.speaker_name, "party": c.party,
                "handle": handle, "photo_url": photo,
                "published_at": c.published_at, "platform": c.platform,
                "text": c.canonical or c.verbatim, "verbatim": c.verbatim,
                "relevance": c.relevance, "why": c.relevance_why or [],
                "subject_id": c.subject_id, "subject_label": s_label,
                "subject_status": s_status, "url": urls.get(c.id),
            }
            for c, handle, photo, s_label, s_status in rows
        ],
    }
