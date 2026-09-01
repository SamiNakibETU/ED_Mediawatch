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

async def all_affiliations(db: AsyncSession) -> dict[int, list[SpeakerAffiliation]]:
    """Toutes les affiliations, groupees par locuteur.

    Une centaine de lignes pour cent treize locuteurs : on charge le tout une
    fois par passe plutot que de requeter par declaration. Le N+1 serait ici
    particulierement couteux — l'extraction ecrit par milliers.
    """
    rows = (await db.execute(select(SpeakerAffiliation))).scalars().all()
    grouped: dict[int, list[SpeakerAffiliation]] = {}
    for a in rows:
        grouped.setdefault(a.personality_id, []).append(a)
    return grouped


def party_of(
    grouped: dict[int, list[SpeakerAffiliation]],
    personality,
    when: date | datetime | None,
) -> str | None:
    """Le parti a inscrire sur un propos : celui du jour ou il a ete tenu.

    Ce que ca corrige. Le parti etait fige au moment de l'extraction, pris sur
    la fiche du locuteur — c'est-a-dire son parti AUJOURD'HUI. Une declaration
    d'Eric Ciotti en 2023 se retrouvait donc etiquetee UDR, un parti qui
    n'existait pas encore. Toute comparaison « ce que dit le RN » contre « ce
    que disait LR » etait fausse d'autant, et d'autant plus faussee que le
    corpus remonte loin.

    A defaut d'affiliation couvrant la date, on retombe sur la fiche : mieux
    vaut le parti actuel que pas de parti du tout, et `party_at` a deja epuise
    ce qu'on sait.
    """
    if personality is None:
        return None
    courant = personality.famille or personality.group_code
    return party_at(grouped.get(personality.id), when) or courant
