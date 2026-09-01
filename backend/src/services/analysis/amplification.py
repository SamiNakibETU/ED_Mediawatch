"""Construction des arêtes d'amplification, et lecture de ce qu'elles disent.

Aucun appel de modèle : la typologie est déjà en base (`post_type`) et la cible
a été récupérée par la collecte. Il ne reste qu'à en tirer les conséquences —
c'est la seule couche du plan qui ne coûte rien.

Idempotent : une contrainte d'unicité sur `post_id` fait qu'un post produit au
plus une arête, et rejouer la construction ne duplique rien.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone

import structlog
from sqlalchemy import case, func, select

from src.database import get_session_factory
from src.models.amplification import Amplification
from src.models.personality import Personality
from src.models.post import Post

logger = structlog.get_logger(__name__)

# Un relais nu vaut adhésion ; un relais commenté est ambigu et se lit dans le
# commentaire. Une réponse n'est pas un relais du tout.
AMPLIFYING = ("retweet", "quote")


async def build_amplifications(*, limit: int = 5000) -> dict:
    """Crée les arêtes manquantes. Rend le compte par nature."""
    factory = get_session_factory()
    async with factory() as db:
        déjà = set((await db.execute(select(Amplification.post_id))).scalars().all())
        posts = list((await db.execute(
            select(Post)
            .where(Post.post_type.in_(AMPLIFYING), Post.quoted_handle.isnot(None))
            .order_by(Post.published_at.desc().nullslast())
            .limit(limit)
        )).scalars().all())

        créées: Counter = Counter()
        for p in posts:
            if p.id in déjà:
                continue
            db.add(Amplification(
                post_id=p.id,
                personality_id=p.personality_id,
                target_handle=p.quoted_handle,
                target_url=p.quoted_url,
                kind=p.post_type,
                published_at=p.published_at,
            ))
            créées[p.post_type] += 1
        await db.commit()

        # Ce qui reste hors du graphe faute de cible : la collecte n'a pas
        # toujours pu récupérer l'auteur relayé (compte fermé, post supprimé).
        # Le dire évite de lire un graphe incomplet comme un graphe complet.
        sans_cible = await db.scalar(
            select(func.count()).select_from(Post)
            .where(Post.post_type.in_(AMPLIFYING), Post.quoted_handle.is_(None))
        ) or 0

    stats = {"retweets": créées["retweet"], "quotes": créées["quote"],
             "created": sum(créées.values()), "without_target": sans_cible}
    logger.info("amplification.built", **stats)
    return stats


async def who_they_amplify(personality_id: int, *, limit: int = 20) -> list[dict]:
    """Les comptes qu'une figure relaie, du plus au moins souvent."""
    factory = get_session_factory()
    async with factory() as db:
        rows = (await db.execute(
            select(Amplification.target_handle,
                   func.count(),
                   # `case` et non `func.iif` : iif() est une fonction SQLite.
                   # Postgres l'ignore, et la requête n'aurait échoué qu'en
                   # production, à l'ouverture d'une fiche — jamais ici, où les
                   # tests tournent sur SQLite.
                   func.sum(case((Amplification.kind == "retweet", 1), else_=0)),
                   func.min(Amplification.published_at),
                   func.max(Amplification.published_at))
            .where(Amplification.personality_id == personality_id)
            .group_by(Amplification.target_handle)
            .order_by(func.count().desc())
            .limit(limit)
        )).all()

    return [
        {"handle": h, "n": n, "n_retweets": int(rt or 0), "n_quotes": n - int(rt or 0),
         "first_seen": lo, "last_seen": hi}
        for h, n, rt, lo, hi in rows
    ]


async def new_voices(*, days: int = 90, min_relays: int = 2) -> list[dict]:
    """Les comptes qu'une figure s'est mise à relayer RÉCEMMENT.

    C'est la lecture éditoriale de ce graphe, et elle n'existe nulle part
    ailleurs : un compte qu'on relayait jamais et qu'on relaie maintenant est un
    déplacement, daté et sourcé. On ne dit pas ce qu'il signifie — on le montre.

    Deux garde-fous. Un seul relais peut être un accident, d'où `min_relays`. Et
    une figure entrée dans le corpus il y a deux mois aurait toutes ses voix
    « nouvelles » : on écarte celles dont la collecte ne couvre pas la période
    antérieure.
    """
    seuil = datetime.now(timezone.utc) - timedelta(days=days)
    factory = get_session_factory()
    async with factory() as db:
        rows = (await db.execute(
            select(Amplification.personality_id, Personality.full_name,
                   Amplification.target_handle,
                   func.count(),
                   func.min(Amplification.published_at),
                   func.max(Amplification.published_at))
            .join(Personality, Personality.id == Amplification.personality_id)
            .where(Amplification.published_at.isnot(None))
            .group_by(Amplification.personality_id, Amplification.target_handle)
        )).all()

        # Étendue de collecte par figure : sans elle, « nouveau » confondrait
        # un changement de comportement avec un début de collecte.
        étendues = dict(((pid, lo) for pid, lo in (await db.execute(
            select(Amplification.personality_id, func.min(Amplification.published_at))
            .group_by(Amplification.personality_id)
        )).all()))

    def _aware(dt):
        return dt if dt is None or dt.tzinfo else dt.replace(tzinfo=timezone.utc)

    out = []
    for pid, nom, handle, n, lo, hi in rows:
        lo, hi = _aware(lo), _aware(hi)
        début = _aware(étendues.get(pid))
        if n < min_relays or lo is None or lo < seuil:
            continue
        # La collecte doit couvrir la période d'avant, sinon on ne peut pas dire
        # que la voix est nouvelle.
        if début is None or début > seuil:
            continue
        out.append({"personality_id": pid, "speaker": nom, "handle": handle,
                    "n": n, "first_seen": lo, "last_seen": hi})
    out.sort(key=lambda d: -d["n"])
    return out
