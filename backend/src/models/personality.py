"""A monitored far-right personality (RN/UDR deputy or key figure)."""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.models.base import Base, TimestampMixin


class Personality(Base, TimestampMixin):
    __tablename__ = "personalities"

    id: Mapped[int] = mapped_column(primary_key=True)

    full_name: Mapped[str] = mapped_column(String(200), nullable=False)
    # X / Twitter handle WITHOUT the leading "@" (e.g. "MLP_officiel").
    handle: Mapped[str | None] = mapped_column(String(100), unique=True, index=True)

    # Affiliation
    group_code: Mapped[str] = mapped_column(String(20), nullable=False)  # RN, UDR, FIGURE
    group_long: Mapped[str | None] = mapped_column(String(200))
    # Fine-grained family (curated): Officiel, RN, UDR, Reconquete, Droite radicale,
    # Identitaire, Polemiste, Influenceur, Groupe...
    famille: Mapped[str | None] = mapped_column(String(40))
    role: Mapped[str | None] = mapped_column(String(160))  # depute, president, essayiste...
    # Handle verification status: verifie | a_confirmer | an_2024 | fiable
    verif: Mapped[str | None] = mapped_column(String(20))

    # Metadata (mostly from assemblee-nationale.fr)
    circo: Mapped[str | None] = mapped_column(String(200))
    departement: Mapped[str | None] = mapped_column(String(120))
    photo_url: Mapped[str | None] = mapped_column(String(500))
    an_id: Mapped[str | None] = mapped_column(String(40))  # Assemblée Nationale id

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # --- Santé de collecte (C4) — rend visible un handle muet/bloqué récurrent ---
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_collected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # 'ok' (timeline récupérée) | 'blocked' (toutes instances KO) | 'error'
    last_status: Mapped[str | None] = mapped_column(String(16))
    consecutive_failures: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_error: Mapped[str | None] = mapped_column(String(200))

    posts: Mapped[list["Post"]] = relationship(  # noqa: F821
        back_populates="personality", cascade="all, delete-orphan"
    )

    __table_args__ = (Index("ix_personalities_group", "group_code"),)

    def __repr__(self) -> str:
        return f"<Personality {self.full_name} (@{self.handle}, {self.group_code})>"
