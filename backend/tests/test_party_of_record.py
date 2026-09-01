"""Un propos ne change pas de parti quand son auteur en change.

C'est la condition de toute comparaison dans la durée. Le parti était figé à
l'extraction, lu sur la fiche du locuteur — donc son parti *aujourd'hui*. Éric
Ciotti a présidé Les Républicains jusqu'en juin 2024 ; tout ce qu'il a dit avant
portait néanmoins l'étiquette UDR, un parti qui n'existait pas encore. Compter
« ce que dit l'UDR » revenait à lui attribuer deux ans de propos tenus ailleurs,
et l'erreur grandit à mesure que le corpus remonte.

La règle : le parti d'un propos est celui du jour où il a été tenu.
"""

import asyncio
from datetime import date, datetime, timezone

from sqlalchemy import select

from src.config import get_settings
from src.database import get_engine, get_session_factory, init_db
from src.models.affiliation import SpeakerAffiliation
from src.models.claim import Claim
from src.models.personality import Personality
from src.pipeline.stages import BY_NAME, FREE
from src.services.affiliation import all_affiliations, party_of
from src.services.analysis.party_of_record import fix_claim_parties

_CACHES = (get_settings, get_engine, get_session_factory)

# La bascule réelle : président de LR jusqu'au 12 juin 2024, de l'UDR ensuite.
BASCULE = date(2024, 6, 12)
AVANT = datetime(2023, 3, 1, tzinfo=timezone.utc)
APRES = datetime(2025, 3, 1, tzinfo=timezone.utc)


def _run(tmp_path, monkeypatch, check, *, avec_affiliations=True):
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path / 'parti.db'}")
    for c in _CACHES:
        c.cache_clear()

    async def go():
        await init_db()
        factory = get_session_factory()
        async with factory() as db:
            p = Personality(full_name="Éric Ciotti", handle="ECiotti",
                            group_code="UDR", famille="UDR")
            db.add(p)
            await db.commit()
            await db.refresh(p)
            if avec_affiliations:
                db.add(SpeakerAffiliation(personality_id=p.id, party="LR",
                                          date_start=date(2022, 12, 11), date_end=BASCULE))
                db.add(SpeakerAffiliation(personality_id=p.id, party="UDR",
                                          date_start=BASCULE, date_end=None))
            # Deux propos, de part et d'autre de la bascule, tous deux
            # étiquetés au parti d'aujourd'hui — l'état que produisait
            # l'extraction avant correction.
            for quand in (AVANT, APRES):
                db.add(Claim(platform="x", personality_id=p.id,
                             speaker_name=p.full_name, party="UDR",
                             verbatim=f"propos du {quand:%Y}", claim_type="normatif",
                             published_at=quand, confidence=0.7,
                             dedup_key=f"k{quand:%Y}"))
            await db.commit()
            pid = p.id
        await check(factory, pid)

    try:
        asyncio.run(go())
    finally:
        for c in _CACHES:
            c.cache_clear()


def test_a_claim_keeps_the_party_of_its_day(tmp_path, monkeypatch):
    """Le cas qui motive tout : deux propos du même homme, deux partis."""

    async def check(factory, pid):
        stats = await fix_claim_parties()
        assert stats["corrigees"] == 1, "seul le propos d'avant la bascule est faux"
        async with factory() as db:
            partis = {c.published_at.year: c.party for c in
                      (await db.execute(select(Claim))).scalars().all()}
        assert partis[2023] == "LR", "en 2023, Ciotti présidait Les Républicains"
        assert partis[2025] == "UDR"

    _run(tmp_path, monkeypatch, check)


def test_running_twice_changes_nothing(tmp_path, monkeypatch):
    """L'étape tourne à chaque passe : sans idempotence elle réécrirait le
    corpus entier toutes les quatre heures pour rien."""

    async def check(factory, pid):
        await fix_claim_parties()
        second = await fix_claim_parties()
        assert second["corrigees"] == 0

    _run(tmp_path, monkeypatch, check)


def test_without_dated_affiliations_nothing_is_touched(tmp_path, monkeypatch):
    """Sans affiliation datée, il n'y a rien à résoudre. Recopier la fiche
    donnerait l'illusion d'une vérification là où aucune n'a eu lieu — et
    l'étape rendrait un compte de corrections qui ne corrigent rien."""

    async def check(factory, pid):
        stats = await fix_claim_parties()
        assert stats["corrigees"] == 0
        assert "skipped" in stats

    _run(tmp_path, monkeypatch, check, avec_affiliations=False)


def test_a_date_outside_every_affiliation_falls_back_to_the_file():
    """Un propos antérieur à tout ce qu'on sait du locuteur garde le parti de
    sa fiche : mieux vaut la valeur d'aujourd'hui, faute de mieux, qu'une
    colonne vide qui disparaîtrait de tous les comptes."""

    class Fiche:
        id = 1
        famille = "UDR"
        group_code = "UDR"

    affils = {1: [SpeakerAffiliation(personality_id=1, party="LR",
                                     date_start=date(2022, 12, 11), date_end=BASCULE)]}
    # 2019 : avant la première affiliation connue.
    assert party_of(affils, Fiche(), datetime(2019, 1, 1, tzinfo=timezone.utc)) == "LR"
    assert party_of({}, Fiche(), AVANT) == "UDR"
    assert party_of({}, None, AVANT) is None


def test_the_step_costs_nothing():
    """Aucun appel de modèle : la réponse est en base. Une étape payante ici
    serait un défaut de conception, et le budget la ferait sauter."""
    assert BY_NAME["party_of_record"].cost == FREE
    assert "extract_l0" in BY_NAME["party_of_record"].depends_on


def test_affiliations_load_in_one_query(tmp_path, monkeypatch):
    """L'extraction écrit par milliers : une requête d'affiliation par
    déclaration coûterait plus cher que l'extraction elle-même."""

    async def check(factory, pid):
        async with factory() as db:
            grouped = await all_affiliations(db)
        assert set(grouped) == {pid}
        assert len(grouped[pid]) == 2

    _run(tmp_path, monkeypatch, check)
