"""Le SUJET : l'unité à l'intérieur de laquelle des propos se confrontent.

Un sujet n'est pas un thème (« économie ») mais un objet précis (« l'âge de
départ à la retraite »). Il émerge du corpus au lieu d'être décrété : c'est ce
qui manquait pour que comparer deux déclarations ait un sens.

Le libellé est celui que le LLM donne à l'objet (`Claim.stance_target`), retenu
sous sa forme la plus fréquente dans le groupe — la majorité fait la norme.
"""

from datetime import datetime

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base, TimestampMixin


class Subject(Base, TimestampMixin):
    __tablename__ = "subjects"

    id: Mapped[int] = mapped_column(primary_key=True)
    # Libellé lisible : « l'âge de départ à la retraite ».
    label: Mapped[str] = mapped_column(String(300), index=True)
    # Forme comparable (sans accents/articles) — sert au regroupement exact.
    slug: Mapped[str] = mapped_column(String(300), unique=True, index=True)
    theme: Mapped[str | None] = mapped_column(String(40), index=True)

    # Centroïde des déclarations du sujet : permet de rattacher un nouveau propos
    # sans tout recalculer, et de repérer deux sujets devenus identiques.
    centroid: Mapped[list | None] = mapped_column(JSON)
    entities: Mapped[list | None] = mapped_column(JSON)

    n_claims: Mapped[int] = mapped_column(Integer, default=0)
    n_speakers: Mapped[int] = mapped_column(Integer, default=0)
    # Étendue temporelle : un sujet couvrant deux ans est celui où un revirement
    # peut se lire ; sur trois jours, il n'y a rien à chercher.
    first_seen: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_seen: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Curation humaine : un sujet validé ne se refond plus automatiquement.
    status: Mapped[str] = mapped_column(String(12), default="auto", index=True)
    merged_into_id: Mapped[int | None] = mapped_column(
        ForeignKey("subjects.id", ondelete="SET NULL")
    )
    note: Mapped[str | None] = mapped_column(Text)
