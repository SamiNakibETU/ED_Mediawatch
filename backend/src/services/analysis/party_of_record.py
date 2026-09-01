"""Le parti inscrit sur un propos : celui du jour où il a été tenu.

Ce que cette étape répare. Le parti d'une déclaration était figé à l'extraction,
lu sur la fiche du locuteur — c'est-à-dire son parti *aujourd'hui*. Un propos
d'Éric Ciotti en 2023 se retrouvait donc étiqueté UDR, un parti qui n'existait
pas encore ; les déclarations de Nicolas Bay avant 2022 passaient de RN à
Reconquête rétroactivement. Un observatoire qui compare « ce que dit le RN » à
« ce que disait LR » sur la durée comptait alors des propos dans une colonne où
ils n'ont jamais été tenus, et l'erreur grandit à mesure que le corpus remonte.

L'extraction résout désormais le parti à la date. Restent les déclarations déjà
écrites : elles se corrigent ici, par lots bornés, à chaque passe. L'étape est
gratuite (aucun appel de modèle : la réponse est en base) et idempotente — une
fois le corpus aligné elle ne touche plus rien et le dit.
"""

from __future__ import annotations

import structlog
from sqlalchemy import select

from src.database import get_session_factory
from src.models.claim import Claim
from src.models.personality import Personality
from src.services.affiliation import all_affiliations, party_of

logger = structlog.get_logger(__name__)


async def fix_claim_parties(*, limit: int = 5000) -> dict:
    """Réaligne le parti des déclarations sur la date où elles ont été tenues."""
    factory = get_session_factory()
    async with factory() as db:
        affils = await all_affiliations(db)
        if not affils:
            # Sans affiliations datées, il n'y a rien à résoudre : réécrire le
            # parti à partir de la seule fiche ne ferait que recopier ce qui est
            # déjà là, en donnant l'illusion d'une vérification.
            return {"corrigees": 0, "skipped": "aucune affiliation datée en base"}

        fiches = {f.id: f for f in
                  (await db.execute(select(Personality))).scalars().all()}
        lot = list((await db.execute(
            select(Claim).where(Claim.personality_id.isnot(None))
            .order_by(Claim.id).limit(limit)
        )).scalars().all())

        corrigees = 0
        for c in lot:
            juste = party_of(affils, fiches.get(c.personality_id), c.published_at)
            if juste and juste != c.party:
                c.party = juste
                corrigees += 1
        await db.commit()

    stats = {"corrigees": corrigees, "examinees": len(lot)}
    if corrigees:
        logger.info("party_of_record.fixed", **stats)
    return stats
