"""Dossier vivant d'une personnalité (L2) — synthèse cachée + versionnée.

Cache du résultat d'une synthèse « gros modèle » (RAG sur le Grand Livre de la
figure) : narratif neutre + thèmes + positions + revirements + points de vigilance.
Régénéré À LA DEMANDE (coût borné : 1 appel LLM par figure), jamais à chaque vue.
"""

from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base, TimestampMixin


class Dossier(Base, TimestampMixin):
    __tablename__ = "dossiers"

    id: Mapped[int] = mapped_column(primary_key=True)
    personality_id: Mapped[int] = mapped_column(
        ForeignKey("personalities.id", ondelete="CASCADE"), unique=True, index=True
    )
    # Synthèse narrative neutre (grounded sur les déclarations fournies).
    summary: Mapped[str | None] = mapped_column(Text)
    # Structuré : themes_principaux, positions_cles, revirements, points_de_vigilance + stats.
    data: Mapped[dict | None] = mapped_column(JSON)
    n_claims: Mapped[int] = mapped_column(Integer, default=0)
    # provider:model/prompt_version — traçabilité (méthode versionnée).
    model: Mapped[str | None] = mapped_column(String(80))
    generated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
