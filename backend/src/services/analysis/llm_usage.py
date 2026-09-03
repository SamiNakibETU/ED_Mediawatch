"""Comptabilité LLM + garde-budget (leçons du budget guard PMO).

Trois garanties par construction :
  1. Coûts calculés depuis les tokens RÉELS (`response.usage`), pas une
     heuristique caractères/token.
  2. Le contrôle vit dans la couche d'appel LLM elle-même (`ClaimLLM`) : tous
     les chemins (tier-1, L0, dossier, refine) passent par `check_or_raise()`.
  3. `BudgetExceeded` est levé AVANT l'appel API et n'est jamais avalé par les
     `except Exception` fail-open ; l'appelant l'attrape pour s'arrêter
     proprement (stats + reprise possible), jamais de 500 brut.

Budgets : `LLM_DAILY_BUDGET_USD` / `LLM_MONTHLY_BUDGET_USD` (0 = désactivé).
Un modèle absent de la grille est facturé à la grille prudente ET marqué
`price_unknown` — visible dans /llm/costs au lieu de fausser silencieusement.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone

import structlog
from sqlalchemy import func, select

from src.config import get_settings
from src.database import get_session_factory
from src.models.llm_usage import LlmUsageEvent

logger = structlog.get_logger(__name__)


class BudgetExceeded(RuntimeError):
    """Plafond de dépense LLM atteint — l'appelant doit dégrader, pas crasher."""


class ProviderRefused(RuntimeError):
    """Le fournisseur refuse : crédits épuisés, clé révoquée, accès retiré.

    Distinct du plafond interne, qu'on choisit, et d'une panne passagère, qui
    se répare seule. Celui-ci ne se répare que dehors, et rien ne sert de
    réessayer mille fois — ni de rendre None en silence, ce qui faisait
    rapporter « 0 sujet nommé » comme s'il n'y avait rien à nommer, sur une
    chaîne arrêtée. Vécu le 02/09/2026 : quatre cents appels refusés en 402,
    une passe déclarée « ok », et une une vide.
    """


# Grille $/M tokens (input, output) par sous-chaîne d'identifiant de modèle.
# Vérifier les prix sur openrouter.ai/models avant tout changement de modèle.
# La première sous-chaîne qui matche gagne (ordre = du plus spécifique au moins).
_PRICES: list[tuple[str, tuple[float, float]]] = [
    ("deepseek-v4-flash", (0.0679, 0.168)),  # vérifié openrouter.ai 2026-08-26
    ("deepseek", (0.57, 1.15)),
    ("mimo", (0.14, 0.28)),
    ("gpt-5.6-luna", (0.20, 1.20)),
    ("gpt-5.6-terra", (2.0, 12.0)),
    ("gemini-3.7-flash", (0.375, 1.875)),
    ("gpt-oss-120b", (0.35, 0.75)),
    ("qwen", (0.10, 0.30)),
    ("llama", (0.05, 0.08)),
    ("mistral", (0.10, 0.30)),
    ("claude-haiku", (1.0, 5.0)),
    ("claude-sonnet", (3.0, 15.0)),
]
# Grille prudente pour un modèle inconnu : surestime plutôt que sous-estime.
_UNKNOWN_PRICE = (1.0, 5.0)


def price_for(model: str) -> tuple[tuple[float, float], bool]:
    """(prix (in, out) $/M, connu ?) pour un identifiant de modèle."""
    m = model.lower()
    for needle, price in _PRICES:
        if needle in m:
            return price, True
    return _UNKNOWN_PRICE, False


def estimate_cost(model: str, input_tokens: int, output_tokens: int) -> tuple[float, bool]:
    (p_in, p_out), known = price_for(model)
    cost = (input_tokens * p_in + output_tokens * p_out) / 1_000_000
    return cost, known


class LlmBudget:
    """Somme les événements du jour/mois (UTC) avec un petit cache TTL."""

    CACHE_TTL_SECONDS = 30.0

    def __init__(self) -> None:
        self._cached_at = 0.0
        self._day_usd = 0.0
        self._month_usd = 0.0
        # Dépense enregistrée depuis le dernier refresh (le cache ne doit pas
        # masquer ce que le run courant vient de dépenser).
        self._since_refresh = 0.0

    async def _refresh(self) -> None:
        now = datetime.now(timezone.utc)
        day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        month_start = day_start.replace(day=1)
        factory = get_session_factory()
        async with factory() as db:
            self._day_usd = (
                await db.scalar(
                    select(func.coalesce(func.sum(LlmUsageEvent.cost_usd), 0.0)).where(
                        LlmUsageEvent.ts >= day_start
                    )
                )
            ) or 0.0
            self._month_usd = (
                await db.scalar(
                    select(func.coalesce(func.sum(LlmUsageEvent.cost_usd), 0.0)).where(
                        LlmUsageEvent.ts >= month_start
                    )
                )
            ) or 0.0
        self._since_refresh = 0.0
        self._cached_at = time.monotonic()

    async def check_or_raise(self) -> None:
        """À appeler AVANT chaque appel API. Lève BudgetExceeded si plafond atteint.

        Contrairement au guard PMO : si la DB est injoignable, on REFUSE
        (fail-closed) plutôt que de continuer à dépenser en aveugle.
        """
        s = get_settings()
        daily, monthly = s.llm_daily_budget_usd, s.llm_monthly_budget_usd
        if daily <= 0 and monthly <= 0:
            return
        if time.monotonic() - self._cached_at > self.CACHE_TTL_SECONDS:
            await self._refresh()
        day = self._day_usd + self._since_refresh
        month = self._month_usd + self._since_refresh
        if daily > 0 and day >= daily:
            raise BudgetExceeded(
                f"budget LLM journalier atteint ({day:.2f} $ >= {daily:.2f} $)"
            )
        if monthly > 0 and month >= monthly:
            raise BudgetExceeded(
                f"budget LLM mensuel atteint ({month:.2f} $ >= {monthly:.2f} $)"
            )

    async def record(
        self,
        *,
        provider: str,
        model: str,
        task: str,
        input_tokens: int,
        output_tokens: int,
    ) -> float:
        """Écrit la ligne comptable d'un appel réussi. Retourne le coût $."""
        cost, known = estimate_cost(model, input_tokens, output_tokens)
        if not known:
            logger.warning("llm_usage.price_unknown", model=model)
        factory = get_session_factory()
        async with factory() as db:
            db.add(
                LlmUsageEvent(
                    provider=provider,
                    model=model,
                    task=task,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    cost_usd=cost,
                    price_unknown=not known,
                )
            )
            await db.commit()
        self._since_refresh += cost
        return cost

    async def summary(self) -> dict:
        await self._refresh()
        s = get_settings()
        now = datetime.now(timezone.utc)
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        factory = get_session_factory()
        async with factory() as db:
            rows = (
                await db.execute(
                    select(
                        LlmUsageEvent.provider,
                        LlmUsageEvent.model,
                        LlmUsageEvent.task,
                        func.count(),
                        func.sum(LlmUsageEvent.input_tokens),
                        func.sum(LlmUsageEvent.output_tokens),
                        func.sum(LlmUsageEvent.cost_usd),
                    )
                    .where(LlmUsageEvent.ts >= month_start)
                    .group_by(
                        LlmUsageEvent.provider, LlmUsageEvent.model, LlmUsageEvent.task
                    )
                )
            ).all()
            unknown = (
                await db.scalar(
                    select(func.count()).where(
                        LlmUsageEvent.ts >= month_start,
                        LlmUsageEvent.price_unknown.is_(True),
                    )
                )
            ) or 0
        return {
            "day_usd": round(self._day_usd, 4),
            "month_usd": round(self._month_usd, 4),
            "daily_budget_usd": s.llm_daily_budget_usd,
            "monthly_budget_usd": s.llm_monthly_budget_usd,
            "events_price_unknown_month": unknown,
            "by_model_month": [
                {
                    "provider": r[0],
                    "model": r[1],
                    "task": r[2],
                    "calls": r[3],
                    "input_tokens": int(r[4] or 0),
                    "output_tokens": int(r[5] or 0),
                    "cost_usd": round(r[6] or 0.0, 4),
                }
                for r in rows
            ],
        }


_budget: LlmBudget | None = None


def get_llm_budget() -> LlmBudget:
    global _budget
    if _budget is None:
        _budget = LlmBudget()
    return _budget
