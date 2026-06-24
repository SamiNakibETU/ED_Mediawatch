"""Résolution du « parti à la date » d'un locuteur (critère de métadonnées §5).

Le parti évolue (Ciotti LR→UDR en 2024, Maréchal Reconquête→ID-Libertés…). Un
post/énoncé doit porter le parti du locuteur *à la date de la prise de parole*,
pas son parti actuel. La donnée vit dans `SpeakerAffiliation` (datée) ; ici on
la résout efficacement (un seul chargement groupé pour toute une page).
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.affiliation import SpeakerAffiliation


async def affiliations_for(
    db: AsyncSession, personality_ids: list[int]
) -> dict[int, list[SpeakerAffiliation]]:
    """Charge toutes les affiliations des personnalités données, groupées par id
    (évite le N+1 : un seul SELECT pour une page de posts)."""
    if not personality_ids:
        return {}
    rows = (
        await db.execute(
            select(SpeakerAffiliation).where(
                SpeakerAffiliation.personality_id.in_(set(personality_ids))
            )
        )
    ).scalars().all()
    grouped: dict[int, list[SpeakerAffiliation]] = {}
    for a in rows:
        grouped.setdefault(a.personality_id, []).append(a)
    return grouped


def party_at(
    affils: list[SpeakerAffiliation] | None, when: date | datetime | None
) -> str | None:
    """Parti couvrant `when` parmi les affiliations d'un locuteur.

    À défaut de date ou de couverture : l'affiliation en cours (`date_end` None),
    sinon la plus récente. Renvoie None si on ne sait rien.
    """
    if not affils:
        return None
    d = when.date() if isinstance(when, datetime) else when
    if d is not None:
        for a in affils:
            start_ok = a.date_start is None or a.date_start <= d
            end_ok = a.date_end is None or d <= a.date_end
            if start_ok and end_ok:
                return a.party
    current = [a for a in affils if a.date_end is None]
    if current:
        return current[0].party
    return max(affils, key=lambda a: (a.date_start or date.min)).party
