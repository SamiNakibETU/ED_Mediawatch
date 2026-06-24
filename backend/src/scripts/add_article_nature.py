"""Migration ponctuelle : ajoute la colonne `articles.nature` si absente.

`create_all` ne modifie pas une table existante (pas d'Alembic). Additif et
idempotent ; no-op si la colonne existe déjà.

    railway ssh "python -m src.scripts.add_article_nature"
"""

import asyncio

from sqlalchemy import text

from src.database import get_engine


async def migrate() -> None:
    engine = get_engine()
    async with engine.begin() as conn:
        if engine.dialect.name == "postgresql":
            exists = await conn.scalar(
                text(
                    "SELECT 1 FROM information_schema.columns "
                    "WHERE table_name='articles' AND column_name='nature'"
                )
            )
            if exists:
                print("- articles.nature : déjà présente, ok.")
                return
            await conn.execute(text("ALTER TABLE articles ADD COLUMN nature VARCHAR(20)"))
            await conn.execute(
                text("CREATE INDEX IF NOT EXISTS ix_articles_nature ON articles (nature)")
            )
            print("- articles.nature : ajoutée ✓")
        else:
            print(f"Dialecte {engine.dialect.name} : géré par l'auto-migration SQLite.")


if __name__ == "__main__":
    asyncio.run(migrate())
