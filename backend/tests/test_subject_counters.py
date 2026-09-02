"""Un compteur de sujet est une valeur dérivée : il se recalcule, il ne s'accumule pas.

Vécu le 02/09/2026. La une annonçait « 5 voix · 19 prises de position » pour un
sujet auquel plus aucune déclaration n'était rattachée. Sur 1 087 sujets, 325
portaient un compte faux.

Le mécanisme : une passe de regroupement déplace des déclarations d'un sujet
vers un autre. Elle met à jour les sujets qu'elle vient de bâtir — et laisse les
sujets appauvris avec le compte d'avant. Rien ne signale l'écart, parce que
`n_claims` est écrit, pas calculé.

C'est le pire genre de défaut pour un observatoire : la page affiche un nombre
qui a l'air d'un fait vérifié et qui ne correspond à rien.
"""

import asyncio
from datetime import datetime, timezone

from sqlalchemy import select

from src.config import get_settings
from src.database import get_engine, get_session_factory, init_db
from src.models.claim import Claim
from src.models.subject import Subject
from src.services.analysis.subject_builder import _resync_counters

_CACHES = (get_settings, get_engine, get_session_factory)
QUAND = datetime(2026, 6, 1, tzinfo=timezone.utc)


def _run(tmp_path, monkeypatch, check):
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path / 'cnt.db'}")
    for c in _CACHES:
        c.cache_clear()

    async def go():
        await init_db()
        factory = get_session_factory()
        async with factory() as db:
            garde = Subject(slug="garde", label="Un sujet qui tient",
                            status="labelled", n_claims=99, n_speakers=9)
            vide = Subject(slug="vide", label="Un sujet vidé par la passe",
                           status="labelled", n_claims=19, n_speakers=5)
            db.add_all([garde, vide])
            await db.commit()
            await db.refresh(garde)
            await db.refresh(vide)
            for i, qui in enumerate(("Marine Le Pen", "Sébastien Chenu")):
                db.add(Claim(platform="x", subject_id=garde.id, speaker_name=qui,
                             verbatim=f"propos {i}", claim_type="normatif",
                             published_at=QUAND, confidence=0.7, dedup_key=f"k{i}"))
            await db.commit()
            ids = (garde.id, vide.id)
        await check(factory, ids)

    try:
        asyncio.run(go())
    finally:
        for c in _CACHES:
            c.cache_clear()


def test_the_counter_follows_the_claims_not_the_last_write(tmp_path, monkeypatch):
    """Deux déclarations, deux voix — quel que soit ce que la passe précédente
    avait inscrit."""

    async def check(factory, ids):
        garde_id, _ = ids
        async with factory() as db:
            await _resync_counters(db)
            s = await db.get(Subject, garde_id)
            assert (s.n_claims, s.n_speakers) == (2, 2)
            # SQLite rend des dates naïves : on compare ce qui est comparable.
            assert s.first_seen.replace(tzinfo=None) == QUAND.replace(tzinfo=None)
            assert s.last_seen.replace(tzinfo=None) == QUAND.replace(tzinfo=None)

    _run(tmp_path, monkeypatch, check)


def test_a_subject_without_a_single_claim_is_removed(tmp_path, monkeypatch):
    """Un sujet qui ne porte plus rien n'est pas un sujet vide, c'est un sujet
    qui n'existe plus : ses déclarations sont ailleurs. Le garder revient à
    publier un titre sans contenu — et le sommaire en listait 325."""

    async def check(factory, ids):
        _, vide_id = ids
        async with factory() as db:
            vidés, corrigés = await _resync_counters(db)
            assert vidés == 1
            assert await db.get(Subject, vide_id) is None
            assert corrigés == 1, "le sujet conservé avait lui aussi un faux compte"

    _run(tmp_path, monkeypatch, check)


def test_running_twice_corrects_nothing_the_second_time(tmp_path, monkeypatch):
    """Le recalage tourne à chaque passe : s'il « corrigeait » à chaque fois, on
    ne saurait plus distinguer une dérive réelle d'un bruit de fond."""

    async def check(factory, ids):
        async with factory() as db:
            await _resync_counters(db)
        async with factory() as db:
            vidés, corrigés = await _resync_counters(db)
        assert (vidés, corrigés) == (0, 0)

    _run(tmp_path, monkeypatch, check)
