"""Audit log of each collection run (per scheduler tick).

`kind` ('x' | 'press') désambiguïse les deux types de passe : pour X,
`personalities_polled`/`posts_new` = handles sondés / posts neufs ; pour la
presse, ils portent sources scannées / articles neufs. Lire via `kind`.
"""

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base, utcnow
from src.vocabulary import RunStatus


class CollectionRun(Base):
    __tablename__ = "collection_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    # 'x' | 'press' — type de passe (cf. vocabulary.RunKind).
    kind: Mapped[str | None] = mapped_column(String(10), index=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    status: Mapped[str] = mapped_column(
        String(20), default=RunStatus.RUNNING
    )  # running/completed/error
    instance_used: Mapped[str | None] = mapped_column(String(200))

    personalities_polled: Mapped[int] = mapped_column(Integer, default=0)
    posts_new: Mapped[int] = mapped_column(Integer, default=0)
    errors: Mapped[int] = mapped_column(Integer, default=0)
    notes: Mapped[str | None] = mapped_column(Text)
