"""Niveaux de veille au-dessus de l'item, rattachés au référentiel CAP.

- `Sujet` : sujet PERSISTANT qui accumule des items dans le temps
  (ex. « coût de l'immigration », « plan climatisation »).
- `Actualite` : fait DATÉ qui agrège des réactions (ex. une réforme, une
  séquence médiatique).

Schéma défini dès le MVP (spec §3, §4) ; le rattachement des items se fait par
la classification (§6) et la curation (§7). Référence CAP via `theme_id` ; FK en
SET NULL pour ne jamais détruire un sujet/une actu si la grille évolue.
"""

from datetime import date

from sqlalchemy import Boolean, Date, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base, TimestampMixin


class Sujet(Base, TimestampMixin):
    __tablename__ = "sujets"

    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    label: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    theme_id: Mapped[str | None] = mapped_column(
        ForeignKey("themes.id", ondelete="SET NULL"), index=True
    )
    subtheme_id: Mapped[str | None] = mapped_column(
        ForeignKey("subthemes.id", ondelete="SET NULL")
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    __table_args__ = (Index("ix_sujets_theme", "theme_id"),)


class Actualite(Base, TimestampMixin):
    __tablename__ = "actualites"

    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    label: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    theme_id: Mapped[str | None] = mapped_column(
        ForeignKey("themes.id", ondelete="SET NULL"), index=True
    )
    event_date: Mapped[date | None] = mapped_column(Date, index=True)  # le fait daté

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
