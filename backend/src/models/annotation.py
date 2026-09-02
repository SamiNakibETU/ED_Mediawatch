"""Le codage humain d'une déclaration — l'autre moitié d'une mesure de fiabilité.

Pourquoi une table et pas une colonne. Un alpha se calcule entre CODEURS : avec
une seule colonne « code humain », on ne pourrait jamais en avoir deux, et c'est
précisément le second annotateur indépendant qui manque pour franchir le seuil.
Le protocole de référence en emploie six, avec test de qualification et pilote ;
on en vise deux, ce qui est déjà une autre mesure que celle d'aujourd'hui.

`code` à None n'est pas une absence de réponse : c'est la décision « hors
politique publique », qui est une catégorie à part entière et compte dans le
calcul. L'absence de réponse, elle, est l'absence de ligne.
"""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base, TimestampMixin


class CapAnnotation(Base, TimestampMixin):
    __tablename__ = "cap_annotations"
    __table_args__ = (
        UniqueConstraint("claim_id", "coder", name="uq_annotation_codeur"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    claim_id: Mapped[int] = mapped_column(
        ForeignKey("claims.id", ondelete="CASCADE"), index=True
    )
    # Qui a codé. Un identifiant libre plutôt qu'un compte : ce qui compte pour
    # la mesure est que deux codeurs soient INDÉPENDANTS, pas qu'ils soient
    # authentifiés.
    coder: Mapped[str] = mapped_column(String(40), index=True)
    # Topique majeur CAP, ou None pour « hors politique publique ».
    code: Mapped[int | None] = mapped_column(Integer)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
