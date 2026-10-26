"""Un sujet qui a émergé une semaine donnée sur X, nommé à partir de ses tweets.

Recalculé à chaque passe pour la semaine en cours et la précédente : un sujet de
la semaine n'est pas une donnée durable, c'est une lecture du moment.
"""

from datetime import datetime

from sqlalchemy import JSON, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base, TimestampMixin


class SujetSemaine(Base, TimestampMixin):
    """Un sujet qui a émergé une semaine donnée, nommé à partir de ses tweets."""

    __tablename__ = "sujets_semaine"

    id: Mapped[int] = mapped_column(primary_key=True)
    semaine: Mapped[str] = mapped_column(String(10), index=True)  # « 2026-W43 »
    debut: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ordre: Mapped[int] = mapped_column(Integer)
    libelle: Mapped[str] = mapped_column(String(200))
    theme: Mapped[str | None] = mapped_column(String(20))
    n_tweets: Mapped[int] = mapped_column(Integer)
    n_figures: Mapped[int] = mapped_column(Integer)
    post_ids: Mapped[list] = mapped_column(JSON)
    modele: Mapped[str | None] = mapped_column(String(120))
