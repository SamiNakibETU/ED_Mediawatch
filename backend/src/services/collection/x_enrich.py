"""Enrichissement des tweets tronqués : texte intégral par identifiant (fxtwitter).

Pourquoi : la syndication X coupe à 280 caractères. Les « note tweets » — les
longues prises de position que publient les responsables politiques — arrivent
amputés (vérifié : 304 caractères en syndication, 501 chez fxtwitter pour le
même statut, `is_note_tweet: true`). Une déclaration extraite d'un texte coupé
est une déclaration fausse par omission.

Ce que fait cette passe, pour chaque post marqué `text_truncated` :
  1. demande le tweet complet par identifiant (`x_backfill.fetch_tweet`) ;
  2. si le texte intégral est plus long, remplace le contenu (hash, compte de
     mots, `collected_via` = « syndfx ») et lève le drapeau ;
  3. **invalide les déclarations L0 déjà extraites** de ce post — elles venaient
     d'un texte incomplet, l'extracteur les refera sur le texte entier ;
  4. si fxtwitter rend un texte de même longueur, le tweet faisait vraiment
     ~280 : drapeau levé, rien d'autre.

Rythme poli (série, délai) et borne par passe : fxtwitter n'est pas à nous.
"""

from __future__ import annotations

import asyncio

import httpx
import structlog
from sqlalchemy import delete, select

from src.config import get_settings
from src.database import get_session_factory
from src.models.claim import Claim
from src.models.post import Post
from src.services.collection.x_backfill import fetch_tweet
from src.utils import sha256, status_id

logger = structlog.get_logger(__name__)

COLLECTED_VIA = "syndfx"  # ≤ 8 car.


async def enrich_truncated_posts(limit: int = 400) -> dict:
    """Complète le texte des posts tronqués. Idempotent, borné, résumable."""
    s = get_settings()
    factory = get_session_factory()
    async with factory() as db:
        todo = list(
            (
                await db.execute(
                    select(Post.id, Post.url, Post.personality_id)
                    .where(Post.text_truncated.is_(True))
                    .order_by(Post.published_at.desc().nullslast())
                    .limit(limit)
                )
            ).all()
        )
    if not todo:
        return {"checked": 0, "expanded": 0, "claims_invalidated": 0}

    headers = {"User-Agent": s.user_agent, "Accept": "application/json"}
    expanded = invalidated = unavailable = 0
    async with httpx.AsyncClient(timeout=s.request_timeout_seconds, headers=headers,
                                 follow_redirects=True) as client:
        for pid, url, _ in todo:
            tid = status_id(url)
            handle = (url or "").split("/status/")[0].rsplit("/", 1)[-1]
            data = await fetch_tweet(client, handle, tid) if tid else None
            await asyncio.sleep(s.request_delay_seconds)
            async with factory() as db:
                post = await db.get(Post, pid)
                if post is None:
                    continue
                if data is None:
                    unavailable += 1  # supprimé/privé : on garde le tronqué, drapeau maintenu
                    continue
                full = (data.get("content") or "").strip()
                if len(full) > len(post.content or ""):
                    post.content = full
                    post.content_hash = sha256(full.lower())
                    post.word_count = len(full.split())
                    post.collected_via = COLLECTED_VIA
                    expanded += 1
                    # Les déclarations tirées du texte coupé ne valent plus rien.
                    res = await db.execute(
                        delete(Claim).where(
                            Claim.post_id == pid, Claim.extraction_method == "llm_segment"
                        )
                    )
                    invalidated += res.rowcount or 0
                post.text_truncated = False
                await db.commit()

    stats = {"checked": len(todo), "expanded": expanded,
             "claims_invalidated": invalidated, "unavailable": unavailable}
    logger.info("enrich_truncated.done", **stats)
    return stats
