"""Seed les affiliations partisanes datées des locuteurs.

Par défaut : 1 affiliation « en cours » par personnalité (parti = famille,
date_start = début 17e législature pour les députés). Quelques transitions
historiques connues sont injectées pour démontrer la validité temporelle
(Ciotti LR→UDR, Maréchal Reconquête→ID-Libertés…).

    python -m src.scripts.seed_affiliations
"""

import asyncio
from datetime import date

import structlog
from sqlalchemy import delete, func, select

from src.database import get_session_factory, init_db
from src.models.affiliation import SpeakerAffiliation
from src.models.personality import Personality

logger = structlog.get_logger(__name__)

AN_START = date(2024, 7, 8)  # début 17e législature

# Transitions connues (full_name -> liste d'affiliations datées).
KNOWN_TRANSITIONS: dict[str, list[dict]] = {
    "Éric Ciotti": [
        {"party": "LR", "role": "Président LR", "start": date(2022, 12, 11), "end": date(2024, 6, 12)},
        {"party": "UDR", "role": "Président de l'UDR", "start": date(2024, 6, 12), "end": None},
    ],
    "Marion Marechal": [
        {"party": "Reconquête", "role": "Tête de liste 2024", "start": date(2021, 12, 1), "end": date(2024, 6, 2)},
        {"party": "Identité-Libertés", "role": "Députée européenne", "start": date(2024, 6, 2), "end": None},
    ],
    "Nicolas Bay": [
        {"party": "RN", "role": "Cadre", "start": date(2015, 1, 1), "end": date(2022, 3, 1)},
        {"party": "Reconquête", "role": "Député européen", "start": date(2022, 3, 1), "end": None},
    ],
}


async def seed() -> dict:
    await init_db()
    factory = get_session_factory()
    created = 0

    async with factory() as db:
        await db.execute(delete(SpeakerAffiliation))  # idempotent rebuild
        people = list((await db.execute(select(Personality))).scalars().all())

        for p in people:
            transitions = KNOWN_TRANSITIONS.get(p.full_name)
            if transitions:
                for tr in transitions:
                    db.add(SpeakerAffiliation(
                        personality_id=p.id, party=tr["party"], role=tr["role"],
                        date_start=tr["start"], date_end=tr["end"],
                    ))
                    created += 1
            else:
                party = p.famille if p.famille and p.famille not in {"Officiel", "Groupe"} else (p.group_code or "?")
                db.add(SpeakerAffiliation(
                    personality_id=p.id, party=party, role=p.role,
                    date_start=AN_START if p.group_code in {"RN", "UDR"} else None,
                    date_end=None,
                ))
                created += 1
        await db.commit()

    stats = {"affiliations": created, "personalities": len(people),
             "with_transitions": len(KNOWN_TRANSITIONS)}
    logger.info("seed_affiliations.done", **stats)
    print(f"Affiliations seedées: {stats}")
    return stats


async def ensure_seeded() -> dict:
    """Sème les affiliations si la table est vide, et seulement dans ce cas.

    `seed()` reconstruit tout (il commence par un DELETE) : appelé au démarrage,
    il effacerait à chaque redéploiement les transitions ajoutées à la main. La
    garde « seulement si vide » est ce qui rend l'amorçage sûr en production, où
    personne ne lance de script.

    Sans affiliations en base, le parti d'un propos ne peut pas être résolu à sa
    date : toute la comparaison par parti dans la durée reposerait sur le parti
    du jour, et c'est exactement l'erreur qu'on cherche à écarter.
    """
    factory = get_session_factory()
    async with factory() as db:
        deja = await db.scalar(select(func.count()).select_from(SpeakerAffiliation))
    if deja:
        return {"affiliations": deja, "note": "déjà en base"}
    return await seed()


if __name__ == "__main__":
    asyncio.run(seed())
