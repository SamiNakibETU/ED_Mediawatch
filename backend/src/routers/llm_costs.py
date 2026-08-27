"""Observabilité des coûts LLM : dépense jour/mois, détail par modèle/tâche.

Lecture seule ; les budgets se règlent par env (LLM_DAILY_BUDGET_USD…).
"""

from fastapi import APIRouter

from src.services.analysis.llm_usage import get_llm_budget

router = APIRouter(prefix="/llm", tags=["llm"])


@router.get("/costs")
async def llm_costs() -> dict:
    return await get_llm_budget().summary()
