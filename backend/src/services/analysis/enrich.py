"""L1 — enrichissement des déclarations (thème + référent), ZÉRO coût API.

Deux passes gratuites/cheap sur les claims du Grand Livre :
  1. **thème/sous-thème déterministe** (lexique CAP, sans LLM) — affine/complète le
     thème grossier rendu par L0 ;
  2. **rattachement au référent** par **cosinus EN MÉMOIRE** sur les embeddings
     DÉJÀ calculés (`embed_claims` + `embed_referents`) — aucun nouvel appel API.

Le `referent_key` est la clé de blocking : c'est ce qui fait entrer une déclaration
(de TOUS types, pas seulement chiffrée) dans la détection de contradictions (A3).
"""

from __future__ import annotations

import structlog
from sqlalchemy import select

from src.database import get_session_factory
from src.models.claim import Claim
from src.models.referentiel import Referent, Subtheme
from src.services.analysis.embeddings import cosine
from src.services.classification.theme_classifier import get_classifier

logger = structlog.get_logger(__name__)

# Seuil conservateur de rattachement au référent (précision > rappel ; la
# validation humaine tranche ensuite). Réglable.
_REFERENT_MIN_COSINE = 0.5


async def enrich_claims(limit: int = 5000) -> dict:
    clf = get_classifier()
    factory = get_session_factory()
    themed = referred = 0

    # 1) Thème/sous-thème déterministe (gratuit) sur les claims sans thème.
    async with factory() as db:
        claims = list((await db.execute(
            select(Claim).where(Claim.theme.is_(None)).limit(limit)
        )).scalars().all())
        for c in claims:
            res = clf.classify(c.canonical or c.verbatim or "")
            if res["theme"]:
                c.theme = res["theme"]
                if res["subtheme"]:
                    c.subtheme = res["subtheme"]
                themed += 1
        await db.commit()

    # 2) Référent par cosinus EN MÉMOIRE (réutilise les embeddings déjà calculés).
    async with factory() as db:
        refs = list((await db.execute(
            select(Referent).where(Referent.embedding.isnot(None))
        )).scalars().all())
        if not refs:
            return {"themed": themed, "referred": 0, "note": "aucun référent embeddé"}
        # référent_key -> (theme_id, subtheme_id) pour propager le rattachement.
        ref_meta = {
            k: (theme, sub) for k, theme, sub in (await db.execute(
                select(Referent.key, Subtheme.theme_id, Subtheme.id)
                .join(Subtheme, Referent.subtheme_id == Subtheme.id)
            )).all()
        }
        claims = list((await db.execute(
            select(Claim).where(
                Claim.embedding.isnot(None), Claim.referent_key.is_(None)
            ).limit(limit)
        )).scalars().all())
        for c in claims:
            best_key, best_score = None, 0.0
            for r in refs:
                s = cosine(c.embedding, r.embedding)
                if s > best_score:
                    best_score, best_key = s, r.key
            if best_key and best_score >= _REFERENT_MIN_COSINE:
                c.referent_key = best_key
                theme, sub = ref_meta.get(best_key, (None, None))
                if theme and not c.theme:
                    c.theme = theme
                if sub and not c.subtheme:
                    c.subtheme = sub
                referred += 1
        await db.commit()

    stats = {"themed": themed, "referred": referred, "min_cosine": _REFERENT_MIN_COSINE}
    logger.info("enrich.done", **stats)
    return stats
