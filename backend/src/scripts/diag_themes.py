"""Sonde : répartition thématique des items classés (posts X + articles presse).

À lancer après une passe `/classify` pour MESURER sur données réelles (cadre §7).
Non destructif.

    railway ssh "python -m src.scripts.diag_themes"
"""

import asyncio

from sqlalchemy import func, select

from src.database import get_session_factory
from src.models.article import Article
from src.models.post import Post


def _bar(n: int, total: int, width: int = 30) -> str:
    filled = (n * width // total) if total else 0
    return "█" * filled + "·" * (width - filled)


async def _dist(db, model, label: str) -> None:
    total = await db.scalar(select(func.count(model.id))) or 0
    classed = await db.scalar(
        select(func.count(model.id)).where(model.theme.isnot(None))
    ) or 0
    print(f"\n=== {label} : {classed}/{total} classés ({100 * classed // max(total, 1)}%) ===")
    rows = (
        await db.execute(
            select(model.theme, func.count(model.id))
            .where(model.theme.isnot(None))
            .group_by(model.theme)
            .order_by(func.count(model.id).desc())
        )
    ).all()
    for theme, n in rows:
        print(f"  {theme:22} {n:5}  {_bar(n, classed)}")
    if total - classed:
        print(f"  {'(non classé)':22} {total - classed:5}")


async def main() -> None:
    factory = get_session_factory()
    async with factory() as db:
        await _dist(db, Post, "X / posts")
        await _dist(db, Article, "Presse / articles")


if __name__ == "__main__":
    asyncio.run(main())
