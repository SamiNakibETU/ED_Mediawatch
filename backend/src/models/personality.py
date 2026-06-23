"""A monitored far-right personality (RN/UDR deputy or key figure)."""

from sqlalchemy import Boolean, Index, String
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

    posts: Mapped[list["Post"]] = relationship(  # noqa: F821
        back_populates="personality", cascade="all, delete-orphan"
    )

    __table_args__ = (Index("ix_personalities_group", "group_code"),)

    def __repr__(self) -> str:
        return f"<Personality {self.full_name} (@{self.handle}, {self.group_code})>"
