"""Trace d'exécution du pipeline — pour qu'on puisse répondre « où ça bloque ».

Sans cette trace, un corpus qui n'avance plus est un mystère : on relance des
scripts au hasard. Chaque étape écrit ici ce qu'elle a fait, combien de temps,
ce qu'elle a produit et pourquoi elle s'est arrêtée.
"""

from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.models.base import Base


class PipelineRun(Base):
    __tablename__ = "pipeline_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Signe de vie du processus qui exécute ce run, rafraîchi en continu.
    # Un processus tué ne peut pas mentir : un run « running » sans battement
    # récent est mort, et on peut le dire sans deviner.
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # scheduled | manual
    trigger: Mapped[str] = mapped_column(String(16), default="manual")
    # Périmètre demandé : « free » (aucun coût LLM) ou « full ».
    scope: Mapped[str] = mapped_column(String(16), default="free")
    # running | ok | failed | budget_exceeded | interrupted
    status: Mapped[str] = mapped_column(String(16), default="running", index=True)
    # Coût LLM imputable à ce run (delta mesuré sur le ledger).
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)

    steps: Mapped[list["PipelineStep"]] = relationship(
        back_populates="run", cascade="all, delete-orphan", lazy="selectin"
    )


class PipelineStep(Base):
    __tablename__ = "pipeline_steps"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(
        ForeignKey("pipeline_runs.id", ondelete="CASCADE"), index=True
    )
    stage: Mapped[str] = mapped_column(String(40), index=True)
    # ok | skipped | failed | budget_exceeded
    status: Mapped[str] = mapped_column(String(20), default="ok")
    duration_s: Mapped[float] = mapped_column(Float, default=0.0)
    # Statistiques rendues par l'étape : ce qu'elle a réellement produit.
    stats: Mapped[dict | None] = mapped_column(JSON)
    detail: Mapped[str | None] = mapped_column(Text)

    run: Mapped[PipelineRun] = relationship(back_populates="steps")
