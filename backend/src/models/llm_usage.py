"""Événement d'usage LLM : la ligne comptable d'un appel API.

Chaque appel (gate tier-1, segmentation L0, dossier L2, refine) écrit une ligne
avec les tokens RÉELS renvoyés par le provider (jamais d'heuristique) et le coût
estimé depuis la grille tarifaire. Le budget guard somme ces lignes (jour/mois).
"""

from datetime import datetime, timezone

from sqlalchemy import DateTime, Float, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base


class LlmUsageEvent(Base):
    __tablename__ = "llm_usage_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    ts: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    provider: Mapped[str] = mapped_column(String(30), nullable=False)
    model: Mapped[str] = mapped_column(String(120), nullable=False)
    # Tâche appelante : tier1_gate | l0_segment | dossier | refine
    task: Mapped[str] = mapped_column(String(30), nullable=False)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    # Vrai si le modèle est absent de la grille tarifaire (coût = grille prudente).
    price_unknown: Mapped[bool] = mapped_column(default=False)

    __table_args__ = (Index("ix_llm_usage_ts", "ts"),)
