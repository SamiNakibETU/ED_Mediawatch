"""Garde d'ambiguïté du rattachement au référent (L1).

Le rattachement est la clé de blocking : tous les claims d'un même `referent_key`
sont comparés entre eux par le détecteur. Un mauvais rattachement ne range donc
pas mal un claim, il fabrique une FAUSSE contradiction. Quand deux référents sont
à égalité, s'abstenir est le comportement correct.
"""

import asyncio

from sqlalchemy import select

from src.config import get_settings
from src.database import get_engine, get_session_factory, init_db
from src.models.claim import Claim
from src.models.referentiel import Referent, Subtheme, Theme
from src.services.analysis.enrich import enrich_claims

_CACHES = (get_settings, get_engine, get_session_factory)


def _seed_taxonomy(db) -> None:
    db.add(Theme(id="eco", label="Économie"))
    db.add(Subtheme(id="retraites", theme_id="eco", label="Retraites"))


def _claim(vec, key):
    return Claim(
        platform="x", verbatim=f"verbatim {key}", claim_type="normatif",
        embedding=vec, extraction_method="llm_segment", dedup_key=key,
    )


def _run(tmp_path, monkeypatch, db_name, seed, assertion):
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path / db_name}")
    for c in _CACHES:
        c.cache_clear()

    async def run():
        await init_db()
        factory = get_session_factory()
        async with factory() as db:
            _seed_taxonomy(db)
            seed(db)
            await db.commit()
        stats = await enrich_claims()
        async with factory() as db:
            claims = {
                c.dedup_key: c
                for c in (await db.execute(select(Claim))).scalars().all()
            }
        assertion(stats, claims)

    try:
        asyncio.run(run())
    finally:
        for c in _CACHES:
            c.cache_clear()


def test_ambiguous_referents_are_skipped(tmp_path, monkeypatch):
    def seed(db):
        # Deux référents quasi identiques (le cas des doublons de grille que
        # `fusion_candidates` est censé faire curer).
        db.add(Referent(key="age_retraite", subtheme_id="retraites",
                        label="Âge de départ", unit="annees",
                        embedding=[1.0, 0.0, 0.0]))
        db.add(Referent(key="age_legal", subtheme_id="retraites",
                        label="Âge légal", unit="annees",
                        embedding=[0.999, 0.01, 0.0]))
        db.add(_claim([1.0, 0.005, 0.0], "ambigu"))

    def check(stats, claims):
        assert stats["referred"] == 0
        assert stats["ambiguous_skipped"] == 1
        assert claims["ambigu"].referent_key is None

    _run(tmp_path, monkeypatch, "amb.db", seed, check)


def test_clear_winner_is_linked(tmp_path, monkeypatch):
    def seed(db):
        db.add(Referent(key="age_retraite", subtheme_id="retraites",
                        label="Âge de départ", unit="annees",
                        embedding=[1.0, 0.0, 0.0]))
        db.add(Referent(key="dette", subtheme_id="retraites",
                        label="Dette publique", unit="pct",
                        embedding=[0.0, 1.0, 0.0]))
        db.add(_claim([0.98, 0.05, 0.0], "net"))

    def check(stats, claims):
        assert stats["referred"] == 1
        assert stats["ambiguous_skipped"] == 0
        c = claims["net"]
        assert c.referent_key == "age_retraite"
        # Le rattachement propage la taxonomie du référent.
        assert c.theme == "eco"
        assert c.subtheme == "retraites"

    _run(tmp_path, monkeypatch, "net.db", seed, check)
