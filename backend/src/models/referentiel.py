"""Référentiel thématique versionné : Theme → Subtheme → Referent.

Un `Referent` est un « compteur » : une grandeur canonique suivie dans le temps
(coût de l'immigration, nb d'expulsions promis, prix de l'électricité…). Sa
`referent_key` est la clé de comparaison des claims (blocking). Versionné
(`version`) pour rejouer/auditer l'évolution de la grille.
"""

from sqlalchemy import JSON, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.models.base import Base, TimestampMixin


class Theme(Base, TimestampMixin):
    __tablename__ = "themes"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)  # slug
    label: Mapped[str] = mapped_column(String(120), nullable=False)
    order: Mapped[int] = mapped_column(Integer, default=0)
    version: Mapped[str] = mapped_column(String(20), default="")
    # Alignement Comparative Agendas Project (cadre §2) : code du grand thème CAP
    # (1-10, 12-21, 23 — numérotation d'origine non consécutive) + saillance ED.
    code: Mapped[int | None] = mapped_column(Integer, index=True)
    salience: Mapped[str | None] = mapped_column(String(20))  # basse|moyenne|haute|tres_haute

    subthemes: Mapped[list["Subtheme"]] = relationship(
        back_populates="theme", cascade="all, delete-orphan"
    )


class Subtheme(Base, TimestampMixin):
    __tablename__ = "subthemes"

    id: Mapped[str] = mapped_column(String(60), primary_key=True)  # slug
    theme_id: Mapped[str] = mapped_column(ForeignKey("themes.id", ondelete="CASCADE"))
    label: Mapped[str] = mapped_column(String(160), nullable=False)

    theme: Mapped["Theme"] = relationship(back_populates="subthemes")
    referents: Mapped[list["Referent"]] = relationship(
        back_populates="subtheme", cascade="all, delete-orphan"
    )


class Referent(Base, TimestampMixin):
    __tablename__ = "referents"

    # referent_key canonique, ex. "immigration::cout::france::montant_annuel_eur"
    key: Mapped[str] = mapped_column(String(160), primary_key=True)
    subtheme_id: Mapped[str] = mapped_column(
        ForeignKey("subthemes.id", ondelete="CASCADE"), index=True
    )
    label: Mapped[str] = mapped_column(String(200), nullable=False)
    unit: Mapped[str] = mapped_column(String(60))  # milliards_eur_par_an, pct, position…
    version: Mapped[str] = mapped_column(String(20), default="")
    # Embedding du label (JSON en SQLite ; VECTOR(1024) + pgvector au déploiement).
    embedding: Mapped[list | None] = mapped_column(JSON)

    subtheme: Mapped["Subtheme"] = relationship(back_populates="referents")
