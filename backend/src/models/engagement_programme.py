"""Un engagement du programme, rangé dans le même référentiel que les déclarations.

La table se reconstruit à partir de `data/programme/*.json`, versionnés dans le
dépôt : c'est là qu'un engagement se relit et se corrige, pas en base. Chaque
ligne garde le livret, la page et la phrase exacte, pour qu'on puisse ouvrir le
PDF à la bonne page et vérifier.
"""

from sqlalchemy import Float, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base, TimestampMixin


class EngagementProgramme(Base, TimestampMixin):
    __tablename__ = "engagements_programme"

    id: Mapped[int] = mapped_column(primary_key=True)
    # « rn-2022 » : le parti et l'élection. `parti` sert à confronter une
    # déclaration au programme de son propre camp.
    source: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    parti: Mapped[str] = mapped_column(String(20), nullable=False)
    annee: Mapped[int] = mapped_column(Integer, nullable=False)
    livret: Mapped[str] = mapped_column(String(120), nullable=False)
    page: Mapped[int | None] = mapped_column(Integer)

    enjeu: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    position: Mapped[str | None] = mapped_column(String(40))
    objet: Mapped[str | None] = mapped_column(String(200))
    modalite: Mapped[str | None] = mapped_column(String(12))
    valeur: Mapped[float | None] = mapped_column(Float)
    unite: Mapped[str | None] = mapped_column(String(40))
    verbatim: Mapped[str] = mapped_column(Text, nullable=False)

    lecteur: Mapped[str | None] = mapped_column(String(160))
    # Empreinte du fichier source : la table se recharge quand le fichier change.
    empreinte: Mapped[str] = mapped_column(String(64), nullable=False)

    __table_args__ = (Index("ix_engagements_source_enjeu", "source", "enjeu"),)
