"""Recherche de voisins — pgvector en production, force brute en local.

Le verrou de montée en charge : le rapprochement de déclarations comparait chaque
vecteur à tous les autres en Python. Sur le corpus actuel c'est déjà ~1,5 million
de cosinus par passe (3 112 déclarations × 500 sujets) ; à 50 000 déclarations
c'est inexploitable. Le calcul doit descendre dans la base.

Deux implémentations derrière la même interface, choisies à l'exécution :

* **PostgreSQL + pgvector** — extension, colonne `vector(384)` et index HNSW
  créés à la demande, recherche par `<=>` (distance cosinus). Le tout est
  ADDITIF : la colonne JSON reste la source de vérité, le vecteur en est une
  projection. Aucune migration destructive, cohérent avec la doctrine du projet.
* **SQLite** — force brute en mémoire, identique au comportement actuel. Le
  développement local n'a pas besoin d'un index, et exiger Postgres pour lancer
  les tests coûterait plus qu'il ne rapporte.

Le code appelant ignore laquelle tourne : c'est ce qui permet de passer à
l'échelle sans réécrire la logique d'analyse.
"""

from __future__ import annotations

import structlog
from sqlalchemy import text

from src.config import get_settings
from src.database import get_engine, get_session_factory

logger = structlog.get_logger(__name__)

# La dimension appartient au backend d'embedding, pas a ce module : MiniLM
# local en produit 384, Cohere multilingue v3 en produit 1 024. Codee en dur
# ici, elle creait une colonne `vector(384)` qui refusait les vecteurs Cohere —
# une panne qui n'apparait qu'en production, et seulement si la cle marche.
async def current_dim() -> int:
    """La dimension des vecteurs qui EXISTENT, à défaut celle qu'annonce le
    backend.

    L'ordre compte, et il a coûté une panne. `get_embedder().dim()` annonce ce
    que le backend produirait s'il marchait : en production, avec une clé Cohere
    refusée, il répondait 1 024 alors qu'il ne rendait plus rien. La colonne
    existante, elle, était en 384. L'index tentait donc d'y écrire des vecteurs
    de 1 024 et échouait à chaque passe, sur des données que personne n'avait
    changées.

    Un vecteur déjà en base est un fait ; la déclaration du backend est une
    intention. On lit le fait quand il existe.
    """
    from sqlalchemy import select

    from src.models.claim import Claim
    from src.services.analysis.embeddings import get_embedder

    factory = get_session_factory()
    async with factory() as db:
        vec = (await db.execute(
            select(Claim.embedding).where(Claim.embedding.isnot(None)).limit(1)
        )).scalars().first()
    if isinstance(vec, list) and vec:
        return len(vec)
    return get_embedder().dim()


def is_postgres() -> bool:
    return get_settings().database_url.startswith(("postgres", "postgresql"))


class VectorIndex:
    """Interface commune : trouver les k plus proches d'un vecteur."""

    async def ensure_ready(self, dim: int | None = None) -> dict:
        raise NotImplementedError

    async def sync(self, limit: int = 5000) -> dict:
        raise NotImplementedError

    async def nearest(
        self, embedding: list[float], *, k: int = 20, min_score: float = 0.0,
        exclude_ids: set[int] | None = None,
    ) -> list[tuple[int, float]]:
        raise NotImplementedError


class PgVectorIndex(VectorIndex):
    """Index HNSW dans PostgreSQL. Toute la DDL est idempotente."""

    async def _actual_dim(self) -> int | None:
        """La dimension de la colonne vectorielle telle qu'elle est en base."""
        engine = get_engine()
        async with engine.begin() as conn:
            try:
                row = (await conn.execute(text(
                    "SELECT a.atttypmod FROM pg_attribute a "
                    "JOIN pg_class c ON c.oid = a.attrelid "
                    "WHERE c.relname = 'claims' AND a.attname = 'embedding_vec'"
                ))).first()
            except Exception:  # noqa: BLE001
                return None
        return int(row[0]) if row and row[0] and row[0] > 0 else None

    async def ensure_ready(self, dim: int | None = None) -> dict:
        dim = dim or await current_dim()
        # Une colonne pgvector ne s'élargit pas : sa dimension fait partie du
        # type. Quand elle ne correspond plus, on la refait — sans perte, parce
        # que `embedding_vec` n'est qu'une projection de `claims.embedding`, que
        # `sync()` recopie ensuite. Sans ça, l'index échouait à chaque passe et
        # rien en aval ne repartait.
        actuelle = await self._actual_dim()
        if actuelle is not None and actuelle != dim:
            logger.warning("vector_index.dimension_changed", etait=actuelle, devient=dim)
            engine = get_engine()
            async with engine.begin() as conn:
                for stmt in ("DROP INDEX IF EXISTS ix_claims_embedding_vec",
                             "ALTER TABLE claims DROP COLUMN IF EXISTS embedding_vec"):
                    try:
                        await conn.execute(text(stmt))
                    except Exception as exc:  # noqa: BLE001
                        logger.warning("vector_index.recreate_failed",
                                       stmt=stmt[:40], error=str(exc)[:120])
        engine = get_engine()
        steps: list[str] = []
        async with engine.begin() as conn:
            # Chaque étape dans son SAVEPOINT : sur Postgres, un échec avorte
            # toute la transaction — une extension absente ne doit pas empêcher
            # le reste de démarrer.
            for label, stmt in (
                ("extension", "CREATE EXTENSION IF NOT EXISTS vector"),
                ("colonne", f"ALTER TABLE claims ADD COLUMN IF NOT EXISTS embedding_vec vector({dim})"),
                ("index", "CREATE INDEX IF NOT EXISTS ix_claims_embedding_vec "
                          "ON claims USING hnsw (embedding_vec vector_cosine_ops)"),
            ):
                try:
                    await conn.execute(text(stmt))
                    steps.append(label)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("vector_index.ddl_failed", step=label,
                                   error=str(exc)[:200])
                    return {"ready": False, "done": steps, "failed": label,
                            "error": str(exc)[:200]}
        return {"ready": True, "done": steps, "dim": dim}

    async def sync(self, limit: int = 5000) -> dict:
        """Projette les embeddings JSON dans la colonne vectorielle. Idempotent."""
        factory = get_session_factory()
        async with factory() as db:
            rows = list((await db.execute(text(
                "SELECT id, embedding FROM claims "
                "WHERE embedding IS NOT NULL AND embedding_vec IS NULL LIMIT :n"
            ), {"n": limit})).all())
            for claim_id, emb in rows:
                vec = emb if isinstance(emb, list) else None
                if not vec:
                    continue
                await db.execute(
                    text("UPDATE claims SET embedding_vec = :v ::vector WHERE id = :i"),
                    {"v": str(vec), "i": claim_id},
                )
            await db.commit()
        return {"synced": len(rows)}

    async def nearest(
        self, embedding: list[float], *, k: int = 20, min_score: float = 0.0,
        exclude_ids: set[int] | None = None,
    ) -> list[tuple[int, float]]:
        # `<=>` rend une DISTANCE cosinus dans [0,2] ; la similarité est 1 - d.
        factory = get_session_factory()
        async with factory() as db:
            rows = list((await db.execute(text(
                "SELECT id, 1 - (embedding_vec <=> :v ::vector) AS score "
                "FROM claims WHERE embedding_vec IS NOT NULL "
                "ORDER BY embedding_vec <=> :v ::vector LIMIT :k"
            ), {"v": str(embedding), "k": k + len(exclude_ids or ())})).all())
        excl = exclude_ids or set()
        return [(i, float(s)) for i, s in rows if i not in excl and s >= min_score][:k]


class BruteForceIndex(VectorIndex):
    """Repli local : comparaison en mémoire, sans index.

    Correct mais quadratique — acceptable en développement, jamais en production
    au-delà de quelques milliers de vecteurs.
    """

    async def ensure_ready(self, dim: int | None = None) -> dict:
        return {"ready": True, "done": [], "note": "force brute (SQLite)"}

    async def sync(self, limit: int = 5000) -> dict:
        return {"synced": 0, "note": "rien à projeter hors PostgreSQL"}

    async def nearest(
        self, embedding: list[float], *, k: int = 20, min_score: float = 0.0,
        exclude_ids: set[int] | None = None,
    ) -> list[tuple[int, float]]:
        from sqlalchemy import select

        from src.models.claim import Claim
        from src.services.analysis.subject_clustering import cosine

        factory = get_session_factory()
        async with factory() as db:
            rows = list((await db.execute(
                select(Claim.id, Claim.embedding).where(Claim.embedding.isnot(None))
            )).all())
        excl = exclude_ids or set()
        scored = [
            (i, cosine(embedding, e)) for i, e in rows if i not in excl and e
        ]
        scored = [(i, s) for i, s in scored if s >= min_score]
        scored.sort(key=lambda t: -t[1])
        return scored[:k]


_index: VectorIndex | None = None


def get_index() -> VectorIndex:
    global _index
    if _index is None:
        _index = PgVectorIndex() if is_postgres() else BruteForceIndex()
        logger.info("vector_index.selected", backend=type(_index).__name__)
    return _index


def reset_index() -> None:
    """Force la re-sélection — utile aux tests qui changent de base."""
    global _index
    _index = None
