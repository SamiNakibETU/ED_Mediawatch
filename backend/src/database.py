"""Async SQLAlchemy engine + session factory.

Works with SQLite (local-first) and PostgreSQL (production) unchanged.
"""

from collections.abc import AsyncIterator
from functools import lru_cache

import structlog
from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from src.config import get_settings
from src.models.base import Base

logger = structlog.get_logger(__name__)


@lru_cache
def get_engine() -> AsyncEngine:
    url = get_settings().database_url
    # Railway/Heroku exposent l'URL en `postgresql://` ; le moteur async exige
    # le driver `asyncpg`. On normalise pour accepter les deux formes.
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)

    is_sqlite = url.startswith("sqlite")
    # SQLite has weak concurrency; WAL + a busy timeout let concurrent async
    # collectors write without "database is locked". No-op on PostgreSQL.
    connect_args = {"timeout": 30} if is_sqlite else {}
    engine = create_async_engine(
        url,
        echo=False,
        pool_pre_ping=True,
        connect_args=connect_args,
    )

    if is_sqlite:

        @event.listens_for(engine.sync_engine, "connect")
        def _sqlite_pragmas(dbapi_conn, _record):  # noqa: ANN001
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA busy_timeout=30000")
            cur.execute("PRAGMA synchronous=NORMAL")
            cur.close()

    return engine


@lru_cache
def get_session_factory() -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(
        bind=get_engine(),
        class_=AsyncSession,
        expire_on_commit=False,
    )


def _autoadd_missing_columns(sync_conn) -> None:  # noqa: ANN001
    """Add columns present on the models but missing from existing tables.

    Runs on **SQLite AND PostgreSQL** so the schema can evolve (engagement,
    archive fields, MVP curation/taxonomy tables…) without Alembic and — above
    all — without the local/prod divergence that bit us before: a new column
    worked in SQLite but silently never reached Postgres.

    Discipline:
      * additive only — `ALTER TABLE ADD COLUMN`, never DROP / retype;
      * new columns are added NULLable (the model `default=` applies to new rows
        via the ORM; pre-existing rows get NULL). We never emit NOT NULL, so
        ADD COLUMN is safe on a populated Postgres table;
      * each ALTER runs in its own SAVEPOINT so one failure can't poison the
        boot transaction (on Postgres a failed statement aborts the whole tx).

    `create_all` (called first) already creates brand-new *tables*; this only
    backfills missing *columns* on tables that already exist.
    """
    from sqlalchemy import inspect

    inspector = inspect(sync_conn)
    existing_tables = set(inspector.get_table_names())
    for table in Base.metadata.sorted_tables:
        if table.name not in existing_tables:
            continue
        have = {c["name"] for c in inspector.get_columns(table.name)}
        for col in table.columns:
            if col.name in have:
                continue
            type_sql = col.type.compile(sync_conn.dialect)
            stmt = f'ALTER TABLE "{table.name}" ADD COLUMN "{col.name}" {type_sql}'
            try:
                with sync_conn.begin_nested():  # savepoint: isolate this ALTER
                    sync_conn.exec_driver_sql(stmt)
                logger.info("schema.column_added", table=table.name, column=col.name)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "schema.column_add_failed",
                    table=table.name, column=col.name, error=str(exc)[:160],
                )


def _widen_narrowed_strings(sync_conn) -> None:  # noqa: ANN001
    """Élargit les colonnes texte devenues trop courtes pour le modèle.

    SQLite n'applique pas la longueur d'un VARCHAR : une valeur trop longue y
    passe sans bruit. Postgres la refuse. C'est exactement ce qui est arrivé à
    `cap_version` — la signature du codeur est passée de 14 à 56 caractères
    quand elle s'est mise à porter le modèle, et le codage CAP a échoué à
    chaque passe en production pendant que la suite de tests restait verte.

    Élargir n'est pas retyper : Postgres allonge un `varchar` sans réécrire la
    table et sans perdre une valeur. Le rétrécissement, lui, reste interdit —
    il tronquerait des données existantes, et c'est la règle que la discipline
    additive protège.
    """
    from sqlalchemy import String, inspect

    if sync_conn.dialect.name == "sqlite":
        return  # rien à élargir : la longueur n'y est pas contraignante

    inspector = inspect(sync_conn)
    existing_tables = set(inspector.get_table_names())
    for table in Base.metadata.sorted_tables:
        if table.name not in existing_tables:
            continue
        actual = {c["name"]: c["type"] for c in inspector.get_columns(table.name)}
        for col in table.columns:
            want = getattr(col.type, "length", None)
            have = getattr(actual.get(col.name), "length", None)
            if not isinstance(col.type, String) or not want or not have or have >= want:
                continue
            stmt = (f'ALTER TABLE "{table.name}" '
                    f'ALTER COLUMN "{col.name}" TYPE VARCHAR({want})')
            try:
                with sync_conn.begin_nested():
                    sync_conn.exec_driver_sql(stmt)
                logger.info("schema.column_widened", table=table.name,
                            column=col.name, was=have, now=want)
            except Exception as exc:  # noqa: BLE001
                logger.warning("schema.column_widen_failed", table=table.name,
                               column=col.name, error=str(exc)[:160])


async def init_db() -> None:
    """Create missing tables, then additively add missing columns.

    No Alembic: additive, idempotent migrations applied at boot on both SQLite
    (local) and PostgreSQL (prod). See `_autoadd_missing_columns` and
    `_widen_narrowed_strings`.
    """
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_autoadd_missing_columns)
        await conn.run_sync(_widen_narrowed_strings)


async def get_db() -> AsyncIterator[AsyncSession]:
    factory = get_session_factory()
    async with factory() as session:
        yield session
