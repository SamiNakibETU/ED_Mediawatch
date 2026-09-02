"""La dimension de l'index doit venir des vecteurs, pas des intentions.

Vécu le 02/09/2026 en production. La clé Cohere était refusée, donc plus aucun
vecteur n'était produit — mais `get_embedder().dim()` répondait 1 024, la
dimension que Cohere PRODUIRAIT s'il répondait. La colonne pgvector, elle, avait
été créée en 384 lors d'un déploiement antérieur. L'index tentait donc d'écrire
des vecteurs de 1 024 dans une colonne de 384 et échouait à chaque passe, sur
des données que personne n'avait touchées :

    asyncpg.exceptions.DataError: expected 384 dimensions, not 1024

Un vecteur déjà en base est un fait ; la déclaration d'un backend est une
intention. On lit le fait quand il existe — ce que le commentaire d'origine du
module promettait déjà sans le faire.
"""

import asyncio
from datetime import datetime, timezone

from src.config import get_settings
from src.database import get_engine, get_session_factory, init_db
from src.models.claim import Claim
from src.services.analysis.vector_index import current_dim

_CACHES = (get_settings, get_engine, get_session_factory)


def _run(tmp_path, monkeypatch, check, *, vecteur=None):
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path / 'dim.db'}")
    for c in _CACHES:
        c.cache_clear()

    async def go():
        await init_db()
        factory = get_session_factory()
        async with factory() as db:
            db.add(Claim(platform="x", speaker_name="Marine Le Pen",
                         verbatim="un propos", claim_type="normatif",
                         embedding=vecteur,
                         published_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
                         confidence=0.7, dedup_key="v1"))
            await db.commit()
        await check()

    try:
        asyncio.run(go())
    finally:
        for c in _CACHES:
            c.cache_clear()


def test_the_dimension_comes_from_a_real_vector(tmp_path, monkeypatch):
    """Le corpus porte des vecteurs de 384 : c'est 384, quoi qu'annonce le
    backend d'embedding — qui peut être configuré sur un modèle qu'il n'arrive
    plus à joindre."""

    async def check():
        assert await current_dim() == 384

    _run(tmp_path, monkeypatch, check, vecteur=[0.1] * 384)


def test_without_any_vector_the_backend_decides(tmp_path, monkeypatch):
    """Corpus neuf : il n'y a pas de fait à lire, la déclaration du backend est
    la seule information disponible — et elle suffit, puisque les premiers
    vecteurs écrits seront les siens."""

    async def check():
        from src.services.analysis.embeddings import get_embedder

        assert await current_dim() == get_embedder().dim()

    _run(tmp_path, monkeypatch, check, vecteur=None)


def test_a_pgvector_column_cannot_be_widened():
    """La dimension fait partie du TYPE d'une colonne pgvector : contrairement à
    un varchar, elle ne s'allonge pas. Il faut refaire la colonne — ce qui est
    sans perte ici, `embedding_vec` n'étant qu'une projection de
    `claims.embedding` que `sync()` recopie ensuite.

    Ce test garde l'intention : si quelqu'un remplace la recréation par un
    ALTER, il verra pourquoi ça ne peut pas marcher.
    """
    import inspect

    from src.services.analysis.vector_index import PgVectorIndex

    source = inspect.getsource(PgVectorIndex.ensure_ready)
    assert "DROP COLUMN IF EXISTS embedding_vec" in source
    assert "ALTER COLUMN" not in source, "une colonne pgvector ne se retype pas"
