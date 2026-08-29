"""Arête d'amplification — qui relaie qui, et quand.

Trois actes de parole, trois traitements différents. Les confondre détruit de
l'information dans les deux sens.

  · **Publication originale** → une déclaration. Ses mots, sa position.
  · **Retweet cité** → une déclaration (le commentaire, qui est de lui) ET une
    arête (l'objet cité, qui ne l'est pas).
  · **Retweet simple** → JAMAIS une déclaration, une arête seulement. Ce ne sont
    pas ses mots. Mais c'est un acte daté, attribué, qui dit qui il porte.
  · **Réponse** → une déclaration, pas d'arête. Répondre n'est pas amplifier.

La littérature justifie cette séparation plutôt qu'un traitement uniforme : la
méta-analyse des travaux sur Twitter conclut que le retweet simple indique très
majoritairement l'accord et l'adhésion — c'est sur cette base qu'on détecte des
communautés politiquement homogènes — tandis que le retweet cité sert des
signaux VARIÉS, approbation comme dénonciation. Traiter les deux pareil ferait
passer une attaque pour un soutien.

Ce que cette table ouvre, et qui n'existe nulle part ailleurs en France : la
trajectoire d'amplification d'une figure. Un compte qui se met à relayer des
sources plus radicales le fait à une date, et cette date est sourcée.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base


class Amplification(Base):
    __tablename__ = "amplifications"

    id: Mapped[int] = mapped_column(primary_key=True)

    # Le post qui porte l'acte. Unique : un post produit au plus une arête, et
    # rejouer la construction ne duplique donc rien.
    post_id: Mapped[int] = mapped_column(
        ForeignKey("posts.id", ondelete="CASCADE"), unique=True, index=True
    )
    personality_id: Mapped[int] = mapped_column(
        ForeignKey("personalities.id", ondelete="CASCADE"), index=True
    )

    # Qui est amplifié. Le handle est la seule identité dont on dispose : la
    # plupart des comptes relayés ne sont pas dans le pool suivi, et c'est
    # justement ce qui rend la mesure intéressante.
    target_handle: Mapped[str] = mapped_column(String(100), index=True)
    target_url: Mapped[str | None] = mapped_column(String(600))

    # « retweet » (relais nu) ou « quote » (relais commenté). La distinction
    # porte tout le sens : le premier vaut adhésion, le second est ambigu et se
    # lit dans le commentaire, qui existe par ailleurs comme déclaration.
    kind: Mapped[str] = mapped_column(String(10), index=True)

    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)

    __table_args__ = (
        # La question qu'on pose : qui untel amplifie-t-il, et depuis quand.
        Index("ix_ampli_who_when", "personality_id", "published_at"),
    )
