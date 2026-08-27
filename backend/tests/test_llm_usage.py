"""Comptabilité LLM + garde-budget : coûts réels, plafonds, arrêt propre.

Les trois garanties héritées des leçons PMO : prix depuis la grille (avec
marquage des modèles inconnus au lieu d'une facturation silencieusement fausse),
plafond qui lève AVANT l'appel API, et dépense du run courant visible malgré le
cache TTL.
"""

import asyncio

import pytest

from src.config import get_settings
from src.database import get_engine, get_session_factory, init_db
from src.services.analysis import llm_usage
from src.services.analysis.llm_usage import (
    BudgetExceeded,
    LlmBudget,
    estimate_cost,
    price_for,
)

_CACHES = (get_settings, get_engine, get_session_factory)


def _fresh(tmp_path, monkeypatch, **env):
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path / 'u.db'}")
    for k, v in env.items():
        monkeypatch.setenv(k, str(v))
    for c in _CACHES:
        c.cache_clear()
    llm_usage._budget = None


def test_price_known_models():
    (p_in, p_out), known = price_for("deepseek/deepseek-v4-flash:floor")
    assert known and (p_in, p_out) == (0.0679, 0.168)
    (p_in, p_out), known = price_for("openai/gpt-5.6-luna")
    assert known and (p_in, p_out) == (0.20, 1.20)


def test_price_unknown_model_conservative():
    price, known = price_for("mysterious/model-x")
    assert not known
    assert price == (1.0, 5.0)  # surestime plutôt que sous-estime


def test_estimate_cost_math():
    cost, known = estimate_cost("openai/gpt-5.6-luna", 1_000_000, 1_000_000)
    assert known
    assert cost == pytest.approx(0.20 + 1.20)


def test_budget_records_and_raises(tmp_path, monkeypatch):
    _fresh(tmp_path, monkeypatch, LLM_DAILY_BUDGET_USD="0.001",
           LLM_MONTHLY_BUDGET_USD="0")

    async def run():
        await init_db()
        budget = LlmBudget()
        # Sous le plafond : passe.
        await budget.check_or_raise()
        # Dépense réelle enregistrée (10k in / 2k out sur Luna ≈ 0,0044 $).
        cost = await budget.record(
            provider="openrouter", model="openai/gpt-5.6-luna", task="l0_segment",
            input_tokens=10_000, output_tokens=2_000,
        )
        assert cost > 0.001
        # Le cache TTL ne masque pas la dépense du run courant → plafond levé.
        with pytest.raises(BudgetExceeded):
            await budget.check_or_raise()
        # Et après refresh DB aussi (persistance vérifiée).
        budget2 = LlmBudget()
        with pytest.raises(BudgetExceeded):
            await budget2.check_or_raise()

    try:
        asyncio.run(run())
    finally:
        for c in _CACHES:
            c.cache_clear()
        llm_usage._budget = None


def test_budget_disabled_never_raises(tmp_path, monkeypatch):
    _fresh(tmp_path, monkeypatch, LLM_DAILY_BUDGET_USD="0",
           LLM_MONTHLY_BUDGET_USD="0")

    async def run():
        await init_db()
        budget = LlmBudget()
        await budget.record(
            provider="openrouter", model="openai/gpt-5.6-luna", task="dossier",
            input_tokens=10_000_000, output_tokens=10_000_000,
        )
        await budget.check_or_raise()  # budgets à 0 = désactivés

    try:
        asyncio.run(run())
    finally:
        for c in _CACHES:
            c.cache_clear()
        llm_usage._budget = None


def test_summary_flags_unknown_prices(tmp_path, monkeypatch):
    _fresh(tmp_path, monkeypatch, LLM_DAILY_BUDGET_USD="5",
           LLM_MONTHLY_BUDGET_USD="60")

    async def run():
        await init_db()
        budget = LlmBudget()
        await budget.record(provider="openrouter", model="mysterious/model-x",
                            task="tier1_gate", input_tokens=100, output_tokens=10)
        s = await budget.summary()
        assert s["events_price_unknown_month"] == 1
        assert s["month_usd"] > 0
        assert s["by_model_month"][0]["model"] == "mysterious/model-x"

    try:
        asyncio.run(run())
    finally:
        for c in _CACHES:
            c.cache_clear()
        llm_usage._budget = None
