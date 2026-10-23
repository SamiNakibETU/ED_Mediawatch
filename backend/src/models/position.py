"""Une position lue dans une prise de parole, sur un enjeu du registre.

Une ligne par couple (post, enjeu), y compris quand le texte ne prend pas
position : `position` reste alors NULL. C'est la marque que le post a été lu,
pour ne pas le repayer à chaque passe. Un échec d'appel, lui, n'écrit rien.
"""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base, TimestampMixin


class Position(Base, TimestampMixin):
    __tablename__ = "positions"

    id: Mapped[int] = mapped_column(primary_key=True)
    post_id: Mapped[int] = mapped_column(
        ForeignKey("posts.id", ondelete="CASCADE"), index=True
    )
    personality_id: Mapped[int] = mapped_column(
        ForeignKey("personalities.id", ondelete="CASCADE"), index=True
    )
    enjeu: Mapped[str] = mapped_column(String(40), nullable=False)
    # Code d'un cran de l'échelle de l'enjeu, ou NULL : lu, sans position.
    position: Mapped[str | None] = mapped_column(String(40))
    # « explicite » : la position est dite. « implicite » : elle se déduit sans
    # ambiguïté du texte. Le reste n'est pas une position.
    certitude: Mapped[str | None] = mapped_column(String(12))
    # Le fragment exact du tweet qui porte la position, vérifié dans le texte.
    verbatim: Mapped[str | None] = mapped_column(Text)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Signature du lecteur : référentiel et modèle. Sans elle, on ne sait plus
    # ce qui a produit quoi quand l'un des deux change.
    lecteur: Mapped[str | None] = mapped_column(String(120))

    __table_args__ = (
        UniqueConstraint("post_id", "enjeu", name="uq_position_post_enjeu"),
        Index("ix_positions_enjeu_figure", "enjeu", "personality_id", "published_at"),
    )
