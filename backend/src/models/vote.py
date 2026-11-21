"""Les scrutins publics de l'Assemblée nationale et le vote de chaque député du panel.

Source : data.assemblee-nationale.fr (Licence ouverte), 16e et 17e législatures. La table se
reconstruit par `src.scripts.importer_scrutins` ; seuls les votes des figures suivies sont gardés.
Le groupe de chaque vote est celui que l'Assemblée enregistre au jour du scrutin.
"""

from datetime import date

from sqlalchemy import Date, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base, TimestampMixin


class Scrutin(Base, TimestampMixin):
    __tablename__ = "scrutins"

    uid: Mapped[str] = mapped_column(String(40), primary_key=True)     # VTANR5L17V1234
    legislature: Mapped[int] = mapped_column(Integer, nullable=False)
    numero: Mapped[int] = mapped_column(Integer, nullable=False)
    date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    titre: Mapped[str] = mapped_column(Text, nullable=False)
    # SPO ordinaire, SPS solennel, MOC motion de censure
    type: Mapped[str] = mapped_column(String(8), nullable=False)
    sort: Mapped[str | None] = mapped_column(String(20))               # adopté | rejeté
    pour: Mapped[int | None] = mapped_column(Integer)
    contre: Mapped[int | None] = mapped_column(Integer)
    abstentions: Mapped[int | None] = mapped_column(Integer)
    # Enjeu du référentiel repéré dans le titre, par les mots-clés de l'atelier ; à vérifier.
    enjeu: Mapped[str | None] = mapped_column(String(40), index=True)


class Vote(Base, TimestampMixin):
    __tablename__ = "votes"

    id: Mapped[int] = mapped_column(primary_key=True)
    scrutin_uid: Mapped[str] = mapped_column(ForeignKey("scrutins.uid"), nullable=False)
    personality_id: Mapped[int] = mapped_column(ForeignKey("personalities.id"), nullable=False, index=True)
    vote: Mapped[str] = mapped_column(String(12), nullable=False)      # pour | contre | abstention | non_votant
    groupe: Mapped[str | None] = mapped_column(String(20))             # organe du groupe au jour du vote
    # Position la plus fréquente du groupe sur ce scrutin, d'après le décompte publié (aucune en cas d'égalité).
    majorite_groupe: Mapped[str | None] = mapped_column(String(12))
    par_delegation: Mapped[bool | None] = mapped_column()
    cause: Mapped[str | None] = mapped_column(String(40))              # cause d'une absence de vote, si donnée

    __table_args__ = (Index("ix_votes_scrutin_figure", "scrutin_uid", "personality_id", unique=True),)
