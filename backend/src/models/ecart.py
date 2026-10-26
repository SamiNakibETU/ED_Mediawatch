"""Un écart : deux positions qui ne coïncident pas sur un même enjeu.

Trois types, tous déduits par requête sur le registre, jamais par similarité :

* `temps` : une même figure à deux crans différents, à plus d'un mois d'écart ;
* `programme` : une figure à un autre cran que le programme de son parti ;
* `parti` : deux figures du même parti, au même moment, à deux crans différents.

L'écart est gardé en base avec son statut, pour que la relecture humaine
survive aux passes suivantes : une détection nouvelle ne rouvre jamais un écart
déjà tranché.
"""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base, TimestampMixin

STATUTS = ("a_relire", "confirme", "ecarte")


class Ecart(Base, TimestampMixin):
    __tablename__ = "ecarts"

    id: Mapped[int] = mapped_column(primary_key=True)
    type: Mapped[str] = mapped_column(String(12), nullable=False, index=True)
    enjeu: Mapped[str] = mapped_column(String(40), nullable=False, index=True)

    decl_a_id: Mapped[int] = mapped_column(ForeignKey("declarations.id", ondelete="CASCADE"), index=True)
    decl_b_id: Mapped[int | None] = mapped_column(ForeignKey("declarations.id", ondelete="CASCADE"))
    engagement_id: Mapped[int | None] = mapped_column(Integer)  # type `programme`
    figure_a_id: Mapped[int] = mapped_column(Integer, index=True)
    figure_b_id: Mapped[int | None] = mapped_column(Integer)
    parti_a: Mapped[str | None] = mapped_column(String(40))
    parti_b: Mapped[str | None] = mapped_column(String(40))
    date_a: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    date_b: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    position_a: Mapped[str | None] = mapped_column(String(40))
    position_b: Mapped[str | None] = mapped_column(String(40))
    ampleur: Mapped[int] = mapped_column(Integer, default=1)

    statut: Mapped[str] = mapped_column(String(10), default="a_relire", index=True)
    # Le juge relit les deux textes : il vérifie d'abord la lecture de chaque
    # position, puis qualifie l'écart.
    juge_type: Mapped[str | None] = mapped_column(String(20))
    juge_force: Mapped[int | None] = mapped_column(Integer)
    juge_justification: Mapped[str | None] = mapped_column(String(10))  # oui | non | inconnue
    juge_explication: Mapped[str | None] = mapped_column(Text)
    juge_lecteur: Mapped[str | None] = mapped_column(String(120))
    decision_note: Mapped[str | None] = mapped_column(Text)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    cle: Mapped[str] = mapped_column(String(64), unique=True, index=True)
