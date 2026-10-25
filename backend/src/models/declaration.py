"""Une déclaration : une prise de position tirée d'un tweet, rangée dans le référentiel.

Elle vient toujours d'un tweet du compte suivi, jamais d'un article : dans un
article, la parole passe par le journaliste, et on ne peut plus vérifier les
mots du locuteur contre son propre texte. La presse sert à la revue.

Le verbatim est la phrase exacte du tweet qui porte la position. Il est vérifié
contre le texte avant d'être écrit : une déclaration qu'on ne retrouve pas mot
pour mot dans son tweet n'existe pas.
"""

from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base, TimestampMixin


class Declaration(Base, TimestampMixin):
    __tablename__ = "declarations"

    id: Mapped[int] = mapped_column(primary_key=True)
    post_id: Mapped[int] = mapped_column(ForeignKey("posts.id", ondelete="CASCADE"), index=True)
    personality_id: Mapped[int] = mapped_column(
        ForeignKey("personalities.id", ondelete="CASCADE"), index=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Un enjeu du référentiel, ou `hors_liste` avec son objet en clair.
    enjeu: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    position: Mapped[str | None] = mapped_column(String(40))
    objet: Mapped[str | None] = mapped_column(String(200))
    # promet | propose | soutient | refuse | affirme : ce que fait la phrase.
    modalite: Mapped[str | None] = mapped_column(String(12))
    # « explicite » : c'est dit. « implicite » : ça se déduit sans hésitation.
    certitude: Mapped[str | None] = mapped_column(String(12))
    valeur: Mapped[float | None] = mapped_column(Float)
    unite: Mapped[str | None] = mapped_column(String(40))
    verbatim: Mapped[str] = mapped_column(Text, nullable=False)

    # Signature de la lecture : référentiel, consignes, modèle.
    lecteur: Mapped[str | None] = mapped_column(String(160))
    # Clé de dédoublonnage : un même fragment d'un même tweet sur un même enjeu.
    cle: Mapped[str] = mapped_column(String(64), unique=True, index=True)

    __table_args__ = (
        Index("ix_declarations_enjeu_figure", "enjeu", "personality_id", "published_at"),
    )
