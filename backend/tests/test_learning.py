"""Boucle d'apprentissage : les décisions humaines corrigent le juge.

Ce que ces tests protègent : chaque décision de relecteur est un exemple
étiqueté. Sans boucle, le juge répète indéfiniment les mêmes erreurs et sa
précision reste une impression. Avec, la consigne s'aligne sur ce que la
rédaction a déjà tranché — apprentissage réel, sans réentraînement, et surtout
auditable : on peut LIRE ce que le système a appris.
"""

import asyncio
from datetime import datetime, timedelta, timezone

from src.config import get_settings
from src.database import get_engine, get_session_factory, init_db
from src.models.claim import Claim
from src.models.contradiction import Contradiction
from src.services.analysis.learning import (
    MAX_REJECTED,
    few_shot_examples,
    judge_precision,
    judge_system_prompt,
    render_examples,
)

_CACHES = (get_settings, get_engine, get_session_factory)
_NOW = datetime(2026, 8, 28, tzinfo=timezone.utc)


async def _seed(decisions):
    """decisions : liste de (status, reason, method, jours_avant)."""
    await init_db()
    factory = get_session_factory()
    async with factory() as db:
        for i, (status, reason, method, ago) in enumerate(decisions):
            a = Claim(platform="x", verbatim=f"propos A{i}", canonical=f"A{i}",
                      claim_type="normatif", dedup_key=f"a{i}")
            b = Claim(platform="x", verbatim=f"propos B{i}", canonical=f"B{i}",
                      claim_type="normatif", dedup_key=f"b{i}")
            db.add_all([a, b])
            await db.flush()
            db.add(Contradiction(
                claim_a_id=a.id, claim_b_id=b.id, type=1, score=0.9,
                status=status, rejection_reason=reason,
                detection_method=method, rationale="motif du juge",
                validated_at=_NOW - timedelta(days=ago),
            ))
        await db.commit()
    return factory


def _run(tmp_path, monkeypatch, db_name, decisions, check):
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path / db_name}")
    for c in _CACHES:
        c.cache_clear()

    async def go():
        await _seed(decisions)
        await check()

    try:
        asyncio.run(go())
    finally:
        for c in _CACHES:
            c.cache_clear()


# ── Mesure ───────────────────────────────────────────────────────────────

def test_precision_counts_only_decided(tmp_path, monkeypatch):
    """Une file en attente n'est pas un résultat : la compter serait se mentir."""
    decisions = [
        ("confirmed", None, "llm_judge", 1),
        ("rejected", "pas_contradictoire", "llm_judge", 2),
        ("pending", None, "llm_judge", 0),
        ("pending", None, "llm_judge", 0),
    ]

    async def check():
        s = await judge_precision()
        assert s["decided"] == 2          # les pending n'entrent pas
        assert s["pending"] == 2
        assert s["precision"] == 0.5
        assert s["by_method"]["llm_judge"]["precision"] == 0.5

    _run(tmp_path, monkeypatch, "prec.db", decisions, check)


def test_rejection_reasons_point_at_the_faulty_stage(tmp_path, monkeypatch):
    """Chaque motif accuse un étage différent — c'est le diagnostic."""
    decisions = [
        ("rejected", "objets_differents", "llm_judge", 1),
        ("rejected", "objets_differents", "llm_judge", 2),
        ("rejected", "attribution_fausse", "llm_judge", 3),
    ]

    async def check():
        s = await judge_precision()
        top = s["rejection_reasons"][0]
        assert top["reason"] == "objets_differents" and top["n"] == 2
        assert "regroupement" in top["means"]   # désigne le clustering
        assert s["precision"] == 0.0

    _run(tmp_path, monkeypatch, "reasons.db", decisions, check)


# ── Correction ───────────────────────────────────────────────────────────

def test_examples_favour_rejections(tmp_path, monkeypatch):
    """Un juge qui sur-détecte coûte la crédibilité : on lui montre surtout
    ses faux positifs."""
    decisions = [("rejected", "pas_contradictoire", "llm_judge", i) for i in range(8)]
    decisions += [("confirmed", None, "llm_judge", 20 + i) for i in range(4)]

    async def check():
        ex = await few_shot_examples(limit=6)
        rejected = [e for e in ex if e["verdict"] == "pas une contradiction"]
        assert len(rejected) <= MAX_REJECTED     # borné, pas monopolisé
        assert len(ex) <= 6
        assert any(e["verdict"] == "contradiction" for e in ex)

    _run(tmp_path, monkeypatch, "ex.db", decisions, check)


def test_prompt_untouched_when_too_few_decisions(tmp_path, monkeypatch):
    """Deux exemples orientent le modèle sans le corriger : ils ancreraient un
    biais plutôt que de transmettre une doctrine."""
    decisions = [("confirmed", None, "llm_judge", 1), ("rejected", "autre", "llm_judge", 2)]

    async def check():
        base = "CONSIGNE DE BASE"
        assert await judge_system_prompt(base) == base

    _run(tmp_path, monkeypatch, "few.db", decisions, check)


def test_prompt_grows_once_enough_decisions(tmp_path, monkeypatch):
    decisions = [("confirmed", None, "llm_judge", i) for i in range(3)]
    decisions += [("rejected", "pas_contradictoire", "llm_judge", 10 + i) for i in range(3)]

    async def check():
        base = "CONSIGNE DE BASE"
        prompt = await judge_system_prompt(base)
        assert prompt.startswith(base)          # la consigne n'est jamais remplacée
        assert "DÉCISIONS DÉJÀ PRISES" in prompt
        assert "pas une contradiction" in prompt

    _run(tmp_path, monkeypatch, "grow.db", decisions, check)


def test_render_is_empty_without_examples():
    assert render_examples([]) == ""
