"""Une ressource rare sert d'abord ce qu'on publie.

Mesuré le 03/09/2026 : 38 publications archivées sur 10 894, soit 0,3 %. Wayback
accepte quarante reçus toutes les quatre heures ; le fonds demande six semaines.
Pendant ce temps, la file était servie par identifiant décroissant — c'est-à-dire
que le propos affiché en une, celui qu'un lecteur ira vérifier et qu'un compte
peut supprimer demain, attendait son tour derrière dix mille autres.

C'est la même faute que le codage CAP corrigé la veille : une file lente triée
par date d'insertion plutôt que par ce qui compte. Un observatoire cite ce qu'il
peut prouver ; il doit donc prouver d'abord ce qu'il cite.
"""

import asyncio
from datetime import datetime, timezone

from src.config import get_settings
from src.database import get_engine, get_session_factory, init_db
from src.models.claim import Claim
from src.models.post import Post
from src.services.archive.archiver import file_a_archiver

_CACHES = (get_settings, get_engine, get_session_factory)
QUAND = datetime(2026, 6, 1, tzinfo=timezone.utc)


def _run(tmp_path, monkeypatch, check):
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path / 'arch.db'}")
    for c in _CACHES:
        c.cache_clear()

    async def go():
        await init_db()
        factory = get_session_factory()
        async with factory() as db:
            # Trois publications, insérées dans l'ordre inverse de leur intérêt.
            for i, (guid, score) in enumerate(
                (("vieux-mais-capital", 5.4), ("recent-anodin", None), ("dernier-tiede", 1.2))
            ):
                p = Post(personality_id=1, guid=guid, url=f"https://x.com/a/status/{i}",
                         content=guid, published_at=QUAND)
                db.add(p)
                await db.flush()
                if score is not None:
                    db.add(Claim(platform="x", post_id=p.id, speaker_name="Marine Le Pen",
                                 verbatim=guid, claim_type="normatif", confidence=0.7,
                                 dedup_key=guid, published_at=QUAND, relevance=score))
            await db.commit()
        async with factory() as db:
            await check(db)

    try:
        asyncio.run(go())
    finally:
        for c in _CACHES:
            c.cache_clear()


def test_the_queue_serves_the_front_page_before_the_newest(tmp_path, monkeypatch):
    async def check(db):
        file = await file_a_archiver(db, "x", 10)
        assert [p.guid for p in file] == [
            "vieux-mais-capital",   # cité en une : le reçu ne peut pas attendre
            "dernier-tiede",
            "recent-anodin",        # pas encore classé : après, pas avant
        ]

    _run(tmp_path, monkeypatch, check)


def test_an_already_archived_item_never_comes_back(tmp_path, monkeypatch):
    """La passe est reprenable : elle ne redépense pas un reçu déjà obtenu."""
    async def check(db):
        premier = (await file_a_archiver(db, "x", 1))[0]
        premier.archived_at = datetime.now(timezone.utc)
        await db.commit()
        assert [p.guid for p in await file_a_archiver(db, "x", 10)] == [
            "dernier-tiede", "recent-anodin"]

    _run(tmp_path, monkeypatch, check)
