"""Orchestration du pipeline : ordre, isolation des pannes, budget, trace.

Ce que ces tests protègent : la chaîne existait en scripts à lancer à la main
dans un ordre qu'il fallait connaître. Sauter une étape produisait un résultat
vide sans que rien ne le signale — la raison la plus banale pour laquelle
« rien ne marchait ». Les garanties ci-dessous sont ce qui remplace cette
connaissance tacite.
"""

import asyncio

import pytest
from sqlalchemy import select

from src.config import get_settings
from src.database import get_engine, get_session_factory, init_db
from src.models.pipeline_run import PipelineRun, PipelineStep
from src.pipeline import runner, stages as stages_mod
from src.pipeline.stages import FREE, PAID, Stage, resolve_order

_CACHES = (get_settings, get_engine, get_session_factory)


# ── Le graphe ────────────────────────────────────────────────────────────

def test_dependencies_are_pulled_in():
    """Demander le juge exécute tout ce dont il dépend : on ne juge pas sur
    des sujets qui n'ont pas été construits."""
    order = [s.name for s in resolve_order(["judge"])]
    assert "judge" == order[-1]
    for needed in ("extract_l0", "embed", "build_subjects"):
        assert needed in order
    assert order.index("embed") < order.index("build_subjects") < order.index("judge")


def test_l0_runs_after_truncation_repair():
    """Segmenter un tweet coupé à 280 produit des déclarations fausses par
    omission, et la dépense est à refaire."""
    order = [s.name for s in resolve_order()]
    assert order.index("enrich_truncated") < order.index("extract_l0")


def test_unknown_stage_is_rejected():
    with pytest.raises(ValueError, match="inconnue"):
        resolve_order(["etape_qui_nexiste_pas"])


def test_every_stage_declares_known_dependencies():
    """Un graphe qui référence une étape absente ne s'exécute jamais en entier."""
    names = {s.name for s in stages_mod.STAGES}
    for s in stages_mod.STAGES:
        assert set(s.depends_on) <= names, f"{s.name} dépend d'une étape inconnue"
        assert s.cost in (FREE, PAID)


# ── Exécution ────────────────────────────────────────────────────────────

def _fake_stages(monkeypatch, stages):
    monkeypatch.setattr(stages_mod, "STAGES", tuple(stages))
    monkeypatch.setattr(stages_mod, "BY_NAME", {s.name: s for s in stages})


def _run(tmp_path, monkeypatch, db_name, fake, check, **kw):
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path / db_name}")
    for c in _CACHES:
        c.cache_clear()
    _fake_stages(monkeypatch, fake)

    async def go():
        await init_db()
        rep = await run_pipeline_wrapper(**kw)
        factory = get_session_factory()
        async with factory() as db:
            runs = list((await db.execute(select(PipelineRun))).scalars().all())
            steps = list((await db.execute(select(PipelineStep))).scalars().all())
        check(rep, runs, steps)

    async def run_pipeline_wrapper(**kwargs):
        return await runner.run_pipeline(**kwargs)

    try:
        asyncio.run(go())
    finally:
        for c in _CACHES:
            c.cache_clear()


def _stage(name, *, cost=FREE, depends=(), result=None, raises=None):
    async def _run_it():
        if raises is not None:
            raise raises
        return result or {"n": 1}
    return Stage(name, f"Étape {name}", cost, _run_it, depends_on=tuple(depends))


def test_free_scope_never_runs_paid_stages(tmp_path, monkeypatch):
    """Une passe automatique ne doit jamais dépenser sans décision."""
    st = [_stage("gratuite"), _stage("payante", cost=PAID)]

    def check(rep, runs, steps):
        assert [s["stage"] for s in rep["steps"]] == ["gratuite"]
        assert rep["cost_usd"] == 0.0
        assert {s.stage for s in steps} == {"gratuite"}

    _run(tmp_path, monkeypatch, "free.db", st, check, scope="free")


def test_failure_blocks_only_dependents(tmp_path, monkeypatch):
    """Une panne n'arrête que ce qui en dépend ; le reste continue."""
    st = [
        _stage("casse", raises=RuntimeError("boom")),
        _stage("dependante", depends=("casse",)),
        _stage("independante"),
    ]

    def check(rep, runs, steps):
        by = {s["stage"]: s for s in rep["steps"]}
        assert by["casse"]["status"] == "failed"
        assert "boom" in by["casse"]["detail"]
        assert by["dependante"]["status"] == "skipped"
        assert "casse" in by["dependante"]["detail"]
        assert by["independante"]["status"] == "ok"   # non touchée
        assert runs[0].status == "failed"

    _run(tmp_path, monkeypatch, "fail.db", st, check)


def test_budget_stops_paid_but_lets_free_finish(tmp_path, monkeypatch):
    """Un dépassement de budget n'est pas une panne : la protection a marché.
    On ne perd pas une passe entière pour quelques centimes."""
    from src.services.analysis.llm_usage import BudgetExceeded

    st = [
        _stage("payante_1", cost=PAID, raises=BudgetExceeded("plafond atteint")),
        _stage("payante_2", cost=PAID),
        _stage("gratuite_apres"),
    ]

    def check(rep, runs, steps):
        by = {s["stage"]: s for s in rep["steps"]}
        assert by["payante_1"]["status"] == "budget_exceeded"
        assert by["payante_2"]["status"] == "skipped"     # inutile d'insister
        assert by["gratuite_apres"]["status"] == "ok"     # rien ne l'empêche
        assert runs[0].status == "budget_exceeded"        # pas « failed »

    _run(tmp_path, monkeypatch, "budget.db", st, check, scope="full")


def test_every_step_is_recorded(tmp_path, monkeypatch):
    """Sans trace, un corpus qui n'avance plus est un mystère."""
    st = [_stage("une", result={"produits": 42})]

    def check(rep, runs, steps):
        assert len(runs) == 1 and runs[0].finished_at is not None
        assert len(steps) == 1
        assert steps[0].stats == {"produits": 42}
        assert steps[0].duration_s >= 0

    _run(tmp_path, monkeypatch, "trace.db", st, check)


def test_only_runs_named_stages_without_dependencies(tmp_path, monkeypatch):
    """`--only` : exécuter une étape seule quand ses dépendances viennent de tourner.

    Sans cette option, demander l'extraction relance une heure de collecte
    cadencée par le quota X — alors qu'elle vient de finir.
    """
    st = [_stage("collecte"), _stage("analyse", depends=("collecte",))]

    def check(rep, runs, steps):
        assert [s["stage"] for s in rep["steps"]] == ["analyse"]

    _run(tmp_path, monkeypatch, "only.db", st, check, stages=["analyse"], only=True)


def test_without_only_dependencies_are_pulled(tmp_path, monkeypatch):
    """Le défaut reste sûr : les dépendances garantissent des données à jour."""
    st = [_stage("collecte"), _stage("analyse", depends=("collecte",))]

    def check(rep, runs, steps):
        assert [s["stage"] for s in rep["steps"]] == ["collecte", "analyse"]

    _run(tmp_path, monkeypatch, "deps.db", st, check, stages=["analyse"])
