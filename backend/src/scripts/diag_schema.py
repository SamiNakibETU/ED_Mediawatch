"""Sonde de schéma : compare les modèles aux tables réelles et liste les
colonnes manquantes par table. Non destructif.

Après un boot (qui applique `_autoadd_missing_columns` sur SQLite ET Postgres),
la sortie doit être VIDE. Une colonne manquante ici = une migration additive qui
n'a pas pris (le bug local/prod historique). À lancer en prod après déploiement :

    railway ssh "python -m src.scripts.diag_schema"
"""

import asyncio

from sqlalchemy import inspect

from src.config import get_settings
from src.database import get_engine
from src.models.base import Base


def _report(sync_conn) -> dict:
    inspector = inspect(sync_conn)
    existing = set(inspector.get_table_names())
    missing_tables: list[str] = []
    missing_columns: dict[str, list[str]] = {}
    for table in Base.metadata.sorted_tables:
        if table.name not in existing:
            missing_tables.append(table.name)
            continue
        have = {c["name"] for c in inspector.get_columns(table.name)}
        gap = [c.name for c in table.columns if c.name not in have]
        if gap:
            missing_columns[table.name] = gap
    return {"missing_tables": missing_tables, "missing_columns": missing_columns}


async def main() -> None:
    engine = get_engine()
    async with engine.connect() as conn:
        report = await conn.run_sync(_report)

    dialect = get_settings().database_url.split("://")[0]
    print(f"Dialecte : {dialect}")
    if not report["missing_tables"] and not report["missing_columns"]:
        print("OK — schéma aligné sur les modèles (aucune table/colonne manquante).")
        return

    if report["missing_tables"]:
        print("TABLES MANQUANTES :", ", ".join(report["missing_tables"]))
    for table, cols in report["missing_columns"].items():
        print(f"COLONNES MANQUANTES [{table}] : {', '.join(cols)}")
    print("\n⚠ Relancer le boot (init_db) ou écrire une migration additive.")


if __name__ == "__main__":
    asyncio.run(main())
