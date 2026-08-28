"""La fiche d'une figure doit être atteignable en entier.

Le défaut corrigé ici : l'en-tête annonçait « 1 445 propos consignés » et
l'API n'en servait jamais que 150, sans plafond visible ni moyen d'aller
chercher la suite. Le reste n'était pas seulement absent de l'écran, il était
inatteignable — et rien ne le disait. Pour un observatoire qui revendique de
tout consigner, une troncature muette est une promesse non tenue.
"""

import asyncio
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from src.config import get_settings
from src.database import get_engine, get_session_factory, init_db
from src.models.claim import Claim
from src.models.personality import Personality
from src.routers.figure import figure_detail

_CACHES = (get_settings, get_engine, get_session_factory)
N_CLAIMS = 25


def _with_figure(tmp_path, monkeypatch, check):
    """Sème une figure et ses propos, puis passe la session à `check`."""
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path / 'fig.db'}")
    for c in _CACHES:
        c.cache_clear()

    async def go():
        await init_db()
        factory = get_session_factory()
        async with factory() as db:
            p = Personality(full_name="Marine Le Pen", handle="mlp_officiel",
                            group_code="RN")
            db.add(p)
            await db.commit()
            await db.refresh(p)
            base = datetime(2026, 8, 1, tzinfo=timezone.utc)
            for i in range(N_CLAIMS):
                db.add(Claim(
                    personality_id=p.id, speaker_name="Marine Le Pen",
                    verbatim=f"Propos numéro {i}", canonical=f"Propos numéro {i}",
                    claim_type="normatif", theme="economie" if i % 2 else "securite",
                    platform="x", published_at=base - timedelta(days=20 * i),
                    dedup_key=f"k{i}", extraction_method="llm_segment",
                ))
            await db.commit()
            await check(db, p.id)

    try:
        asyncio.run(go())
    finally:
        for c in _CACHES:
            c.cache_clear()


def test_total_is_reported_not_just_the_page(tmp_path, monkeypatch):
    """Sans le total, une page pleine est indiscernable d'un corpus épuisé."""
    async def check(db, fid):
        d = await figure_detail(fid, theme=None, limit=10, offset=0, db=db)
        assert d["timeline_total"] == N_CLAIMS
        assert d["timeline_count"] == 10

    _with_figure(tmp_path, monkeypatch, check)


def test_offset_advances_through_the_history(tmp_path, monkeypatch):
    """Chaque page doit apporter des propos que la précédente n'avait pas."""
    async def check(db, fid):
        def texts(d):
            return [c["canonical"] for m in d["timeline"] for c in m["claims"]]

        first = texts(await figure_detail(fid, theme=None, limit=10, offset=0, db=db))
        second = texts(await figure_detail(fid, theme=None, limit=10, offset=10, db=db))
        assert len(first) == len(second) == 10
        assert not set(first) & set(second)

    _with_figure(tmp_path, monkeypatch, check)


def test_last_page_is_short_and_exhausts_the_corpus(tmp_path, monkeypatch):
    """Le bouton « afficher la suite » se calcule sur ce reste : s'il ne tombe
    pas à zéro, il reste affiché pour toujours."""
    async def check(db, fid):
        d = await figure_detail(fid, theme=None, limit=10, offset=20, db=db)
        assert d["timeline_count"] == N_CLAIMS - 20
        assert d["timeline_offset"] + d["timeline_count"] == d["timeline_total"]

    _with_figure(tmp_path, monkeypatch, check)


def test_theme_filter_narrows_the_total_too(tmp_path, monkeypatch):
    """Le total doit suivre le filtre. Rendre le total global sous un filtre
    thématique laisserait le bouton promettre des propos qu'il ne servira pas."""
    async def check(db, fid):
        d = await figure_detail(fid, theme="economie", limit=100, offset=0, db=db)
        assert 0 < d["timeline_total"] < N_CLAIMS
        assert d["timeline_count"] == d["timeline_total"]
        themes = {c["theme"] for m in d["timeline"] for c in m["claims"]}
        assert themes == {"economie"}

    _with_figure(tmp_path, monkeypatch, check)
