"""Embeddings sur les claims (A0) — substrat du blocking sémantique / near-dup.

Réutilise `CohereEmbedder` + `cosine` (services/analysis/embeddings.py). À l'échelle
du corpus, le cosinus en mémoire suffit ; la colonne `Claim.embedding` (JSON)
deviendra `VECTOR(1024)` + pgvector sans changer cette logique (décision déjà actée).

Usages :
  * `embed_claims()` — calcule + cache l'embedding manquant de chaque claim (idempotent) ;
  * `near_duplicate_groups()` — regroupe les claims quasi identiques (même assertion
    répétée sur plusieurs sources/reposts) → évite de gonfler Le Compteur, et sert
    de base au blocking sémantique inter-référent (A3).
"""

from __future__ import annotations

import structlog
from sqlalchemy import select

from src.database import get_session_factory
from src.models.claim import Claim
from src.services.analysis.embeddings import cosine, get_embedder

logger = structlog.get_logger(__name__)


def _claim_text(c: Claim) -> str:
    """Texte représentatif d'un claim pour l'embedding (canonical sinon verbatim)."""
    return (c.canonical or c.verbatim or "").strip()


async def embed_claims(limit: int = 2000) -> dict:
    """Calcule l'embedding des claims qui n'en ont pas encore (idempotent)."""
    embedder = get_embedder()
    if not embedder.available():
        return {"embedded": 0, "skipped": "cohere indisponible"}

    factory = get_session_factory()
    async with factory() as db:
        todo = list(
            (
                await db.execute(
                    select(Claim).where(Claim.embedding.is_(None)).limit(limit)
                )
            ).scalars().all()
        )
        texts = [_claim_text(c) for c in todo]
        pairs = [(c, t) for c, t in zip(todo, texts) if t]
        if not pairs:
            return {"embedded": 0, "note": "rien à embedder"}
        vectors = await embedder.embed([t for _, t in pairs])
        for (c, _), v in zip(pairs, vectors):
            obj = await db.get(Claim, c.id)
            if obj:
                obj.embedding = v
        await db.commit()
    return {"embedded": len(pairs)}


def _greedy_groups(items: list[tuple[int, list[float]]], threshold: float) -> list[list[int]]:
    """Clustering glouton par cosinus : un item rejoint le 1er groupe assez proche."""
    groups: list[tuple[list[float], list[int]]] = []  # (vecteur-pivot, ids)
    for cid, vec in items:
        placed = False
        for pivot, ids in groups:
            if cosine(vec, pivot) >= threshold:
                ids.append(cid)
                placed = True
                break
        if not placed:
            groups.append((vec, [cid]))
    return [ids for _, ids in groups if len(ids) >= 2]


async def near_duplicate_groups(threshold: float = 0.92) -> list[dict]:
    """Groupes de claims quasi identiques, par bloc de référent (sens + échelle)."""
    factory = get_session_factory()
    async with factory() as db:
        claims = list(
            (
                await db.execute(
                    select(Claim).where(Claim.embedding.isnot(None))
                )
            ).scalars().all()
        )
    by_ref: dict[str | None, list[Claim]] = {}
    for c in claims:
        by_ref.setdefault(c.referent_key, []).append(c)

    by_id = {c.id: c for c in claims}
    out: list[dict] = []
    for ref_key, block in by_ref.items():
        groups = _greedy_groups([(c.id, c.embedding) for c in block], threshold)
        for ids in groups:
            out.append({
                "referent_key": ref_key,
                "count": len(ids),
                "claim_ids": ids,
                "samples": [(by_id[i].verbatim or "")[:120] for i in ids[:3]],
            })
    return sorted(out, key=lambda d: d["count"], reverse=True)
