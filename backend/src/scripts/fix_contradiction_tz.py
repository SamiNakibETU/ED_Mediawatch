"""Migration ponctuelle : passer contradictions.detected_at / validated_at en
`timestamptz` sur une base PostgreSQL déjà créée avec des colonnes naïves.

Contexte : ces deux colonnes avaient été déclarées sans `DateTime(timezone=True)`
(corrigé dans le modèle). asyncpg refuse d'insérer un datetime *aware* dans une
colonne `TIMESTAMP` naïve. `create_all` ne modifie pas une table existante, d'où
ce one-shot. Non destructif (ALTER TYPE, la table de contradictions est vide).
Idempotent et no-op hors PostgreSQL.

    railway ssh "python -m src.scripts.fix_contradiction_tz"
"""

import asyncio

from sqlalchemy import text

from src.database import get_engine

_COLUMNS = ("detected_at", "validated_at")


async def migrate() -> None:
    engine = get_engine()
    if engine.dialect.name != "postgresql":
        print(f"Dialecte {engine.dialect.name} : rien à faire (PostgreSQL uniquement).")
        return

    async with engine.begin() as conn:
        for col in _COLUMNS:
            current = await conn.scalar(
                text(
                    "SELECT data_type FROM information_schema.columns "
                    "WHERE table_name = 'contradictions' AND column_name = :c"
                ),
                {"c": col},
            )
            if current is None:
                print(f"- {col}: colonne absente, ignorée.")
                continue
            if current == "timestamp with time zone":
                print(f"- {col}: déjà timestamptz, ok.")
                continue
            await conn.execute(
                text(
                    f"ALTER TABLE contradictions ALTER COLUMN {col} "
                    f"TYPE timestamptz USING {col} AT TIME ZONE 'UTC'"
                )
            )
            print(f"- {col}: {current} -> timestamptz ✓")
    print("Migration terminée.")


if __name__ == "__main__":
    asyncio.run(migrate())
