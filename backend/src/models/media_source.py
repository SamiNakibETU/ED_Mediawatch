"""A French online media outlet (RSS source), positioned on the spectrum.

`leaning` spans the editorial spectrum the brief asks for — "de Frontières à
Basta", i.e. far-right → far-left — so the analytical layer can later contrast
how each side speaks about the RN.
"""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.models.base import Base, TimestampMixin
from src.vocabulary import Leaning


class MediaSource(Base, TimestampMixin):
    __tablename__ = "media_sources"

    id: Mapped[str] = mapped_column(String(60), primary_key=True)  # slug
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    homepage: Mapped[str | None] = mapped_column(String(400))
    rss_url: Mapped[str] = mapped_column(String(500), nullable=False)

    # national | regional | pure_player | magazine
    category: Mapped[str] = mapped_column(String(40), default="national")
    # far_right | right | center | left | far_left
    leaning: Mapped[str] = mapped_column(String(20), default=Leaning.CENTER)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_collected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # --- Santé de collecte (C4) — rend visible une source muette/cassée ---
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # 'ok' (flux récupéré+parsé) | 'empty' (0 entrée) | 'http_403'… | 'error'
    last_status: Mapped[str | None] = mapped_column(String(16))
    # Échecs consécutifs (>0 = source à surveiller ; 0 = repartie).
    consecutive_failures: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_error: Mapped[str | None] = mapped_column(String(200))

    articles: Mapped[list["Article"]] = relationship(  # noqa: F821
        back_populates="media_source"
    )

    def __repr__(self) -> str:
        return f"<MediaSource {self.id} ({self.leaning})>"
