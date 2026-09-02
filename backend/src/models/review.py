"""La revue d'un sujet sur une période : ce qui s'est dit, et par qui.

Ce que ce modèle n'est pas : un résumé qu'on régénère quand le modèle s'améliore.
Une revue porte une date et un état du corpus ; la réécrire plus tard avec des
déclarations arrivées depuis produirait un texte qui n'a jamais été vrai au
moment qu'il prétend décrire. D'où la clé unique (cadence, période, sujet) : une
période close ne se réécrit pas, elle se complète par la suivante.

Le corps n'est pas du texte libre mais une suite de paragraphes ADOSSÉS à des
déclarations : chacun porte les identifiants de ce qu'il rapporte. Un paragraphe
sans source ne survit pas à la relecture (cf. `review.py`) — c'est la même règle
que pour le verbatim et l'attribution, appliquée à la synthèse.
"""

from datetime import datetime

from sqlalchemy import (
    JSON,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base, TimestampMixin


class Review(Base, TimestampMixin):
    __tablename__ = "reviews"
    __table_args__ = (
        UniqueConstraint("cadence", "period", "subject_id", name="uq_review_periode"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # « hebdomadaire » ou « quotidienne » : la cadence fait partie de l'identité
    # de la revue, pas d'un réglage — les deux peuvent coexister sur un sujet.
    cadence: Mapped[str] = mapped_column(String(16), index=True)
    # Clé lisible et triable : « 2026-W36 », « 2026-09-02 ».
    period: Mapped[str] = mapped_column(String(12), index=True)
    subject_id: Mapped[int] = mapped_column(
        ForeignKey("subjects.id", ondelete="CASCADE"), index=True
    )

    title: Mapped[str] = mapped_column(String(240))
    # [{"texte": "...", "claim_ids": [12, 45]}] — un paragraphe, ses sources.
    body: Mapped[list | None] = mapped_column(JSON)
    claim_ids: Mapped[list | None] = mapped_column(JSON)

    # « brouillon » tant qu'aucun humain n'a relu. La doctrine du juge vaut ici :
    # la machine propose, elle ne publie pas.
    status: Mapped[str] = mapped_column(String(16), default="brouillon", index=True)
    model: Mapped[str | None] = mapped_column(String(80))
    generated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
