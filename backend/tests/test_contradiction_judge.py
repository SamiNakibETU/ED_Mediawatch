"""Juge sémantique : appariement candidat (gratuit) et création d'arêtes.

L'appariement détermine le coût : chaque paire retenue = un appel LLM. Les tests
vérifient la fenêtre de similarité (ni trop loin, ni quasi-doublon), l'exclusion
des paires déjà connues et des locuteurs inconnus, et le fait qu'un verdict non
accusatoire ne crée AUCUNE arête.
"""

import asyncio
from datetime import datetime, timezone

from sqlalchemy import select

from src.config import get_settings
from src.database import get_engine, get_session_factory, init_db
from src.models.claim import Claim
from src.models.contradiction import Contradiction
from src.models.referentiel import Referent, Subtheme, Theme
from src.services.analysis import contradiction_judge as cj
from src.services.analysis.contradiction_judge import (
    ContradictionVerdict,
    _candidate_pairs,
    run_semantic_judging,
)

_CACHES = (get_settings, get_engine, get_session_factory)


def _c(cid, vec, speaker="Marine Test", party="RN"):
    c = Claim(
        platform="x", verbatim=f"v{cid}", claim_type="normatif",
        embedding=vec, speaker_name=speaker, party=party,
        extraction_method="llm_segment", dedup_key=f"k{cid}",
    )
    c.id = cid
    return c


def test_pairs_within_similarity_window():
    # a/b proches mais distincts -> candidat ; a/c orthogonaux -> écartés.
    a, b, c = _c(1, [1.0, 0.0, 0.0]), _c(2, [0.8, 0.6, 0.0]), _c(3, [0.0, 0.0, 1.0])
    pairs = _candidate_pairs([a, b, c], set())
    assert [(p[0].id, p[1].id) for p in pairs] == [(1, 2)]


def test_near_duplicates_excluded():
    # Quasi-identiques : même propos répété, pas un revirement.
    a, b = _c(1, [1.0, 0.0, 0.0]), _c(2, [0.999, 0.01, 0.0])
    assert _candidate_pairs([a, b], set()) == []


def test_known_pairs_skipped():
    a, b = _c(1, [1.0, 0.0, 0.0]), _c(2, [0.8, 0.6, 0.0])
    assert _candidate_pairs([a, b], {(1, 2)}) == []


def test_anonymous_speakers_skipped():
    # Sans locuteur ni parti des deux côtés, aucune imputation n'est possible.
    a = _c(1, [1.0, 0.0, 0.0], speaker=None, party=None)
    b = _c(2, [0.8, 0.6, 0.0], speaker=None, party=None)
    assert _candidate_pairs([a, b], set()) == []


class _FakeLLM:
    """Juge simulé : renvoie le verdict programmé, compte les appels."""

    def __init__(self, verdict: str):
        self.verdict = verdict
        self.calls = 0

    def available(self):
        return True

    async def judge_contradiction(self, prompt: str):
        self.calls += 1
        return ContradictionVerdict(
            verdict=self.verdict, explanation="motif de test", confidence=0.9
        )


def _run_judging(tmp_path, monkeypatch, db_name, verdict, assertion):
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path / db_name}")
    for c in _CACHES:
        c.cache_clear()
    fake = _FakeLLM(verdict)
    monkeypatch.setattr(cj, "get_claim_llm", lambda: fake)

    async def run():
        await init_db()
        factory = get_session_factory()
        async with factory() as db:
            db.add(Theme(id="eco", label="Économie"))
            db.add(Subtheme(id="retraites", theme_id="eco", label="Retraites"))
            db.add(Referent(key="age_retraite", subtheme_id="retraites",
                            label="Âge de départ", unit="annees"))
            # Même locuteur : dates espacées d'un mois, sinon le filtre
            # MIN_GAP_DAYS écarte la paire (un revirement suppose du temps).
            for cid, vec, day, post in ((1, [1.0, 0.0, 0.0], 1, 11), (2, [0.8, 0.6, 0.0], 28, 22)):
                db.add(Claim(
                    platform="x", verbatim=f"position {cid}", claim_type="normatif",
                    canonical=f"position {cid}", embedding=vec,
                    speaker_name="Marine Test", party="RN", personality_id=1,
                    referent_key="age_retraite", post_id=post,
                    published_at=datetime(2026, 1, day, tzinfo=timezone.utc),
                    extraction_method="llm_segment", dedup_key=f"k{cid}",
                ))
            await db.commit()

        stats = await run_semantic_judging()
        async with factory() as db:
            edges = list((await db.execute(select(Contradiction))).scalars().all())
        assertion(stats, edges, fake)

    try:
        asyncio.run(run())
    finally:
        for c in _CACHES:
            c.cache_clear()


def test_contradiction_verdict_creates_edge(tmp_path, monkeypatch):
    def check(stats, edges, fake):
        assert fake.calls == 1
        assert stats["contradictions_new"] == 1
        assert len(edges) == 1
        e = edges[0]
        assert e.status == "pending"          # l'humain tranche
        assert e.detection_method == "llm_judge"
        assert e.judge_version == cj.JUDGE_PROMPT_VERSION
        assert e.type == 1                    # même locuteur, dates différentes
        assert e.rationale == "motif de test"

    _run_judging(tmp_path, monkeypatch, "j1.db", "contradiction", check)


def test_non_accusatory_verdicts_create_nothing(tmp_path, monkeypatch):
    def check(stats, edges, fake):
        assert fake.calls == 1
        assert stats["contradictions_new"] == 0
        assert stats["verdicts"] == {"evolution_assumee": 1}
        assert edges == []

    _run_judging(tmp_path, monkeypatch, "j2.db", "evolution_assumee", check)


def _dated(cid, vec, day, speaker="Marine Test", post_id=None, article_id=None):
    from datetime import datetime, timezone
    c = _c(cid, vec, speaker=speaker)
    c.published_at = datetime(2026, 1, day, tzinfo=timezone.utc)
    c.post_id, c.article_id = post_id, article_id
    return c


def test_same_source_pairs_excluded():
    # Deux déclarations issues du MÊME post : segmentations qui se recouvrent,
    # pas une contradiction (cas réel observé le 26/08).
    a = _dated(1, [1.0, 0.0, 0.0], 1, post_id=77)
    b = _dated(2, [0.8, 0.6, 0.0], 1, post_id=77)
    assert _candidate_pairs([a, b], set()) == []


def test_same_speaker_needs_time_gap():
    # Même locuteur à 2 jours d'écart : trop court pour un revirement.
    a = _dated(1, [1.0, 0.0, 0.0], 1, post_id=1)
    b = _dated(2, [0.8, 0.6, 0.0], 3, post_id=2)
    assert _candidate_pairs([a, b], set()) == []

    # Le même couple à 30 jours d'écart devient un candidat légitime.
    far = _dated(3, [0.8, 0.6, 0.0], 31, post_id=3)
    assert [(p[0].id, p[1].id) for p in _candidate_pairs([a, far], set())] == [(1, 3)]


def test_different_speakers_need_no_gap():
    # Deux locuteurs différents le même jour : divergence légitime à examiner.
    a = _dated(1, [1.0, 0.0, 0.0], 1, speaker="A", post_id=1)
    b = _dated(2, [0.8, 0.6, 0.0], 1, speaker="B", post_id=2)
    assert len(_candidate_pairs([a, b], set())) == 1


def test_candidates_ranked_by_drift_potential_not_similarity():
    """Le budget doit partir sur les revirements, pas sur les redites.

    Trier par similarité fait examiner d'abord les paires qui se ressemblent le
    plus — donc celles qui disent la même chose. On veut l'inverse : même
    locuteur, propos éloignés dans le temps.
    """
    # Les deux paires sont dans la fenêtre de similarité (cos ≈ 0.8) : c'est le
    # classement, pas le filtre, qui doit les départager.
    # Paire A : même jour, locuteurs différents → pas un revirement.
    redite_1 = _dated(1, [1.0, 0.0, 0.0], 1, speaker="A", post_id=1)
    redite_2 = _dated(2, [0.8, 0.6, 0.0], 1, speaker="B", post_id=2)
    # Paire B : MÊME locuteur, un mois d'écart → candidat au drift.
    drift_1 = _dated(3, [0.0, 1.0, 0.0], 1, speaker="C", post_id=3)
    drift_2 = _dated(4, [0.6, 0.8, 0.0], 28, speaker="C", post_id=4)

    pairs = _candidate_pairs([redite_1, redite_2, drift_1, drift_2], set())
    first = pairs[0]
    assert first[0].speaker_name == "C" and first[1].speaker_name == "C"


def test_subject_blocks_use_a_wider_window():
    """Dans un sujet, l'objet commun est acquis : exiger une forte similarité
    sélectionnerait les redites (82 « compatible » sur 100, mesuré)."""
    a = _dated(1, [1.0, 0.0, 0.0], 1, speaker="A", post_id=1)
    b = _dated(2, [0.5, 0.87, 0.0], 1, speaker="B", post_id=2)   # cos ≈ 0.5

    # Hors sujet : trop dissemblables pour être rapprochées par la seule similarité.
    assert _candidate_pairs([a, b], set()) == []
    # Dans un sujet : légitimement candidates, c'est justement la différence
    # qui peut porter une contradiction.
    assert len(_candidate_pairs([a, b], set(), same_subject=True)) == 1


def test_only_comparable_types_are_paired():
    """Une position contredit une position ; une annonce ne contredit rien.

    Mesuré : les meilleures paires candidates étaient « je répondrai le
    2 septembre » contre « regardez mon entretien » — de la communication, qui
    monopolisait le budget du juge sans rien pouvoir produire.
    """
    a = _dated(1, [1.0, 0.0, 0.0], 1, speaker="A", post_id=1)
    b = _dated(2, [0.8, 0.6, 0.0], 1, speaker="B", post_id=2)
    a.claim_type, b.claim_type = "normatif", "predictif"
    assert _candidate_pairs([a, b], set(), same_subject=True) == []

    b.claim_type = "normatif"
    assert len(_candidate_pairs([a, b], set(), same_subject=True)) == 1


def test_positions_and_numbers_rank_above_softer_types():
    """Le budget part d'abord là où la contradiction est la plus défendable."""
    from src.services.analysis.contradiction_judge import _drift_potential

    def pair(t, gap):
        x = _dated(1, [1.0, 0.0, 0.0], 1, speaker="A", post_id=1)
        y = _dated(2, [0.8, 0.6, 0.0], gap, speaker="A", post_id=2)
        x.claim_type = y.claim_type = t
        return (x, y, 0.8)

    ranked = sorted([pair("predictif", 28), pair("normatif", 28)],
                    key=_drift_potential, reverse=True)
    assert ranked[0][0].claim_type == "normatif"
