"""Une contradiction = arête typée entre deux claims (cf specs §4.3 / §3).

Stockée comme table d'arêtes (pas de base graphe au début). `status` porte la
validation humaine : aucune contradiction n'est « publiée » sans confirmation.
"""

from datetime import datetime

from sqlalchemy import (
    Float,
    ForeignKey,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.models.base import Base, utcnow

# Typologie (specs §3). 1,2,3,6 détectés en P2 (numérique/structurel).
TYPE_LABELS = {
    1: "revirement intra-locuteur",
    2: "contradiction intra-parti",
    3: "divergence inter-partis",
    4: "écart au programme",
    5: "contradiction vérité externe",
    6: "variance numérique",
}


class Contradiction(Base):
    __tablename__ = "contradictions"

    id: Mapped[int] = mapped_column(primary_key=True)

    claim_a_id: Mapped[int] = mapped_column(
        ForeignKey("claims.id", ondelete="CASCADE"), index=True
    )
    claim_b_id: Mapped[int] = mapped_column(
        ForeignKey("claims.id", ondelete="CASCADE"), index=True
    )

    referent_key: Mapped[str | None] = mapped_column(String(160), index=True)
    type: Mapped[int] = mapped_column(SmallInteger)  # 1..6
    score: Mapped[float] = mapped_column(Float, default=0.0)
    rationale: Mapped[str | None] = mapped_column(Text)

    # Validation humaine
    status: Mapped[str] = mapped_column(String(12), default="pending", index=True)
    validator: Mapped[str | None] = mapped_column(String(120))
    detected_at: Mapped[datetime] = mapped_column(default=utcnow)
    validated_at: Mapped[datetime | None] = mapped_column(default=None)

    claim_a = relationship("Claim", foreign_keys=[claim_a_id], lazy="selectin")
    claim_b = relationship("Claim", foreign_keys=[claim_b_id], lazy="selectin")

    __table_args__ = (
        UniqueConstraint("claim_a_id", "claim_b_id", name="uq_contradiction_pair"),
    )
