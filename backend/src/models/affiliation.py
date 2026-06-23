"""Affiliation partisane des locuteurs, datée (validité temporelle).

Nécessaire pour la détection « contradiction intra-parti » : l'appartenance
évolue (Ciotti LR→UDR en 2024, Maréchal Reconquête→ID-Libertés…). Un claim doit
être rattaché au parti du locuteur *à la date du claim*, pas à son parti actuel.
"""

from datetime import date

from sqlalchemy import Date, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.models.base import Base, TimestampMixin


class SpeakerAffiliation(Base, TimestampMixin):
    __tablename__ = "speaker_affiliations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    personality_id: Mapped[int] = mapped_column(
        ForeignKey("personalities.id", ondelete="CASCADE"), index=True
    )
    party: Mapped[str] = mapped_column(String(60), nullable=False)
    role: Mapped[str | None] = mapped_column(String(160))
    date_start: Mapped[date | None] = mapped_column(Date)
    date_end: Mapped[date | None] = mapped_column(Date)  # None = en cours

    personality: Mapped["Personality"] = relationship()  # noqa: F821
