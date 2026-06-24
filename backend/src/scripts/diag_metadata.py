"""Sonde de complétude des métadonnées (critère d'acceptation §5).

Mesure, sur les données RÉELLES en base, le taux de remplissage des champs §5
pour X (posts) et la presse (articles, par source). Non destructif. Les trous
(texte court = paywall, thème vide = pas encore classé, reçu absent = archivage
pas passé) orientent le travail. À lancer en prod :

    railway ssh "python -m src.scripts.diag_metadata"
"""

import asyncio

from sqlalchemy import func, select

from src.database import get_session_factory
from src.models.affiliation import SpeakerAffiliation
from src.models.article import Article
from src.models.media_source import MediaSource
from src.models.post import Post

_FULLTEXT_MIN_WORDS = 200  # en-deçà : probablement tronqué (chapô / paywall)


def _pct(n: int, total: int) -> str:
    return f"{(100 * n // total) if total else 0:3d}%"


async def _diag_x(db) -> None:
    posts = list((await db.execute(select(Post))).scalars().all())
    n = len(posts)
    print(f"\n=== X / posts ({n}) ===")
    if not n:
        return
    with_aff = {
        pid for pid in (
            await db.execute(select(SpeakerAffiliation.personality_id).distinct())
        ).scalars().all()
    }
    checks = {
        "date exacte": sum(1 for p in posts if p.published_at),
        "thème classé": sum(1 for p in posts if p.theme),
        "engagement": sum(1 for p in posts if p.likes is not None or p.retweets is not None),
        "média": sum(1 for p in posts if p.media_url),
        "reçu (archive)": sum(1 for p in posts if p.snapshot_url or p.archived_at),
        "parti à la date dispo": sum(1 for p in posts if p.personality_id in with_aff),
    }
    for label, k in checks.items():
        print(f"  {label:24} {_pct(k, n)}  ({k}/{n})")


async def _diag_press(db) -> None:
    sources = {
        s.id: s for s in (await db.execute(select(MediaSource))).scalars().all()
    }
    rows = list(
        (
            await db.execute(
                select(
                    Article.media_source_id,
                    func.count(Article.id),
                    func.sum(func.length(Article.content)),
                )
                .group_by(Article.media_source_id)
            )
        ).all()
    )
    total = await db.scalar(select(func.count(Article.id))) or 0
    print(f"\n=== Presse / articles ({total}) — par source ===")
    print(f"  {'source':22} {'n':>4} {'plein':>6} {'thème':>6} {'auteur':>7} {'reçu':>5} {'figures':>8}")
    for source_id, _cnt, _len in sorted(rows, key=lambda r: -r[1]):
        arts = list(
            (
                await db.execute(
                    select(Article).where(Article.media_source_id == source_id)
                )
            ).scalars().all()
        )
        m = len(arts)
        full = sum(1 for a in arts if (a.word_count or 0) >= _FULLTEXT_MIN_WORDS)
        theme = sum(1 for a in arts if a.theme)
        author = sum(1 for a in arts if a.author)
        receipt = sum(1 for a in arts if a.snapshot_url or a.archived_at)
        figs = sum(1 for a in arts if a.matched_personalities)
        name = (sources.get(source_id).name if sources.get(source_id) else source_id)[:22]
        print(f"  {name:22} {m:>4} {_pct(full, m)} {_pct(theme, m)} {_pct(author, m)} "
              f"{_pct(receipt, m)} {_pct(figs, m)}")
    print(f"\n  (« plein » = >= {_FULLTEXT_MIN_WORDS} mots ; trous attendus : paywalls/403 §11, "
          f"thème vide tant que la classification §6 n'est pas lancée)")


async def main() -> None:
    factory = get_session_factory()
    async with factory() as db:
        await _diag_x(db)
        await _diag_press(db)


if __name__ == "__main__":
    asyncio.run(main())
