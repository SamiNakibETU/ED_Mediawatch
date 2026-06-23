"""Embeddings Cohere — blocking sémantique des référents.

À l'échelle actuelle (~dizaines de référents) un cosinus en mémoire suffit : pas
besoin de pgvector. Au déploiement, la colonne `Referent.embedding` (JSON)
devient `VECTOR(1024)` + index pgvector, sans changer cette logique.

Deux usages :
  * `nearest_referent(phrase)` — rattacher une prise de parole au bon référent
    même quand les mots-clés du lexique ratent (rappel).
  * `fusion_candidates()` — repérer des référents redondants (même objet formulé
    autrement) pour curer la grille (qualité du blocking, cf specs §4.1).
"""

from __future__ import annotations

import math

import structlog
from sqlalchemy import select

from src.config import get_settings
from src.database import get_session_factory
from src.models.referentiel import Referent

logger = structlog.get_logger(__name__)

try:
    import cohere
except Exception:  # noqa: BLE001
    cohere = None


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


class CohereEmbedder:
    def __init__(self) -> None:
        s = get_settings()
        self._model = s.cohere_embed_model
        self._client = (
            cohere.AsyncClientV2(api_key=s.cohere_api_key)
            if (cohere and s.cohere_api_key)
            else None
        )

    def available(self) -> bool:
        return self._client is not None

    async def embed(self, texts: list[str], *, query: bool = False) -> list[list[float]]:
        if not self._client or not texts:
            return []
        resp = await self._client.embed(
            model=self._model,
            texts=texts,
            input_type="search_query" if query else "search_document",
            embedding_types=["float"],
        )
        return list(resp.embeddings.float_)


_embedder: CohereEmbedder | None = None


def get_embedder() -> CohereEmbedder:
    global _embedder
    if _embedder is None:
        _embedder = CohereEmbedder()
    return _embedder


async def embed_referents() -> dict:
    """Calcule + cache l'embedding du label de chaque référent (idempotent)."""
    embedder = get_embedder()
    if not embedder.available():
        return {"embedded": 0, "skipped": "cohere indisponible"}

    factory = get_session_factory()
    async with factory() as db:
        refs = list((await db.execute(select(Referent))).scalars().all())
        todo = [r for r in refs if not r.embedding]
        if not todo:
            return {"embedded": 0, "total": len(refs), "note": "déjà à jour"}
        vectors = await embedder.embed([r.label for r in todo])
        for r, v in zip(todo, vectors):
            r.embedding = v
        await db.commit()
    return {"embedded": len(todo), "total": len(refs)}


async def nearest_referent(sentence: str, top: int = 3) -> list[dict]:
    embedder = get_embedder()
    if not embedder.available():
        return []
    qvec = (await embedder.embed([sentence], query=True))
    if not qvec:
        return []
    q = qvec[0]
    factory = get_session_factory()
    async with factory() as db:
        refs = list(
            (await db.execute(select(Referent).where(Referent.embedding.isnot(None)))).scalars().all()
        )
    scored = sorted(
        ({"key": r.key, "label": r.label, "score": round(cosine(q, r.embedding), 4)} for r in refs),
        key=lambda d: d["score"], reverse=True,
    )
    return scored[:top]


async def fusion_candidates(threshold: float = 0.86) -> list[dict]:
    """Paires de référents sémantiquement proches (candidats à fusion/revue)."""
    factory = get_session_factory()
    async with factory() as db:
        refs = list(
            (await db.execute(select(Referent).where(Referent.embedding.isnot(None)))).scalars().all()
        )
    out: list[dict] = []
    for i in range(len(refs)):
        for j in range(i + 1, len(refs)):
            s = cosine(refs[i].embedding, refs[j].embedding)
            if s >= threshold:
                out.append({
                    "a": refs[i].key, "a_label": refs[i].label,
                    "b": refs[j].key, "b_label": refs[j].label,
                    "score": round(s, 4),
                })
    return sorted(out, key=lambda d: d["score"], reverse=True)
