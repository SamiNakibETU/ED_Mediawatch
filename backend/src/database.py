"""Async SQLAlchemy engine + session factory.

Works with SQLite (local-first) and PostgreSQL (production) unchanged.
"""

from collections.abc import AsyncIterator
from functools import lru_cache

from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from src.config import get_settings
from src.models.base import Base


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
    """Add columns that exist on the models but not yet in the SQLite tables.

    Lets us evolve models iteratively (engagement, archive fields…) without
    losing collected data or hand-writing migrations during the local phase.
    Only handles additive, nullable columns (the only kind we add).
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
            sync_conn.exec_driver_sql(
                f'ALTER TABLE "{table.name}" ADD COLUMN "{col.name}" {type_sql}'
            )


async def init_db() -> None:
    """Create tables if they don't exist (no Alembic for the local slice)."""
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        if get_settings().database_url.startswith("sqlite"):
            await conn.run_sync(_autoadd_missing_columns)


async def get_db() -> AsyncIterator[AsyncSession]:
    factory = get_session_factory()
    async with factory() as session:
        yield session
