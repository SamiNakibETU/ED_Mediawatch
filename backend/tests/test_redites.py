"""Une phrase dite une fois et reprise vingt fois reste une phrase.

Vu le 04/09/2026 sur la page du sujet « l'interdiction du port du voile » :
154 « prises de position consignées », dont une soixantaine de Jean-Philippe
Tanguy disant la même chose. Il n'en a pas pris soixante — il en a pris une, un
dimanche, et vingt rédactions l'ont reprise. Le dédoublonnage existait par
source (`dedup_key` = source + verbatim) et pas entre sources.

Mesuré sur le plus gros sujet du corpus : 71 propos, 18 distincts au seuil 0,93.

Ce que ça cassait au-delà de l'affichage : le juge sémantique cherche des propos
DIFFÉRENTS sur le même objet et plafonne exprès la similarité pour écarter « la
même phrase reformulée ». Sur un corpus aux trois quarts redondant, il passait
son quota à écarter des redites — 24 rapprochements, aucun confirmé.
"""

import asyncio
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from src.config import get_settings
from src.database import get_engine, get_session_factory, init_db
from src.models.claim import Claim
from src.models.subject import Subject
from src.services.analysis.redites import FENETRE_JOURS, fold_redites, grouper

_CACHES = (get_settings, get_engine, get_session_factory)
QUAND = datetime(2026, 8, 30, tzinfo=timezone.utc)


class _Faux:
    """Le strict nécessaire pour `grouper` : ce qu'il lit d'une déclaration."""

    def __init__(self, id, embedding, **kw):
        self.id = id
        self.embedding = embedding
        self.published_at = kw.get("published_at", QUAND)
        self.quote_style = kw.get("quote_style", "rapporte")
        self.platform = kw.get("platform", "press")


def test_the_same_position_carried_by_three_outlets_is_one_position():
    groupes = grouper([
        _Faux(1, [1.0, 0.0, 0.0]),
        _Faux(2, [0.99, 0.02, 0.0]),
        _Faux(3, [0.98, 0.05, 0.0]),
        _Faux(4, [0.0, 1.0, 0.0]),      # autre chose
    ])
    tailles = sorted(len(g) for g in groupes)
    assert tailles == [1, 3]


def test_the_quoted_original_is_kept_over_the_paraphrase():
    """Le représentant est le mieux sourcé, pas le premier venu : une citation
    directe prime sur du discours rapporté, et un post du locuteur sur un
    article — c'est lui qui a parlé, les autres le répètent."""
    groupes = grouper([
        _Faux(10, [1.0, 0.0, 0.0]),
        _Faux(11, [0.99, 0.01, 0.0], quote_style="direct", platform="x"),
        _Faux(12, [0.98, 0.02, 0.0]),
    ])
    assert len(groupes) == 1
    assert groupes[0][0].id == 11


def test_saying_it_again_six_months_later_is_a_second_position():
    """Un locuteur qui redit la même chose des mois plus tard donne une
    information — il n'a pas changé d'avis. Ce n'est pas une reprise de presse,
    et l'écraser ferait disparaître la constance qu'on cherche à mesurer."""
    groupes = grouper([
        _Faux(20, [1.0, 0.0, 0.0]),
        _Faux(21, [1.0, 0.0, 0.0],
              published_at=QUAND + timedelta(days=FENETRE_JOURS + 1)),
    ])
    assert len(groupes) == 2


def test_a_claim_without_a_vector_is_never_folded_away():
    """Sans vecteur, on ne sait pas si c'est une redite. L'inconnu n'est pas une
    reprise — la même règle que partout ailleurs."""
    groupes = grouper([_Faux(30, None), _Faux(31, [1.0, 0.0, 0.0])])
    assert [c.id for g in groupes for c in g] == [31]


def _run(tmp_path, monkeypatch, check):
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path / 'red.db'}")
    for c in _CACHES:
        c.cache_clear()

    async def go():
        await init_db()
        factory = get_session_factory()
        async with factory() as db:
            s = Subject(slug="voile", label="l’interdiction du port du voile",
                        status="labelled", first_seen=QUAND, last_seen=QUAND)
            db.add(s)
            await db.commit()
            await db.refresh(s)
            # Une interview du dimanche, reprise par quatre journaux, plus un
            # propos réellement distinct du même locuteur.
            for i, vec in enumerate(([1.0, 0.0, 0.0], [0.99, 0.02, 0.0],
                                     [0.98, 0.03, 0.0], [0.99, 0.01, 0.0],
                                     [0.0, 1.0, 0.0])):
                db.add(Claim(platform="press", subject_id=s.id, personality_id=1,
                             speaker_name="Jean-Philippe Tanguy", embedding=vec,
                             verbatim=f"propos {i}", claim_type="normatif",
                             confidence=0.7, dedup_key=f"r{i}", published_at=QUAND))
            await db.commit()
            sid = s.id
        await check(factory, sid)

    try:
        asyncio.run(go())
    finally:
        for c in _CACHES:
            c.cache_clear()


def test_the_pass_folds_the_repeats_and_counts_them(tmp_path, monkeypatch):
    """Rien n'est supprimé : les redites restent en base, rattachées à ce
    qu'elles reprennent, et leur nombre devient un signal porté par l'original —
    qu'une phrase soit reprise par vingt journaux dit quelque chose de son
    poids."""

    async def check(factory, sid):
        stats = await fold_redites()
        assert stats == {"prises_de_position": 2, "redites": 3}
        async with factory() as db:
            claims = list((await db.execute(select(Claim))).scalars().all())
        assert len(claims) == 5, "une redite n'est pas supprimée, elle est rattachée"
        tetes = [c for c in claims if c.duplicate_of is None]
        assert sorted(c.n_reprises for c in tetes) == [0, 3]
        assert all(c.duplicate_of in {t.id for t in tetes}
                   for c in claims if c.duplicate_of is not None)

    _run(tmp_path, monkeypatch, check)


def test_the_pass_is_idempotent(tmp_path, monkeypatch):
    """Valeur dérivée : elle se recalcule, elle ne s'accumule pas. La leçon des
    compteurs de sujets vaut ici aussi."""

    async def check(factory, sid):
        premier = await fold_redites()
        second = await fold_redites()
        assert premier == second

    _run(tmp_path, monkeypatch, check)
