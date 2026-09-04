"""Le claim : assertion atomique, datée, attribuée, rattachée à un référent.

Unité d'analyse centrale (cf specs.md §2). En P1 on extrait surtout les claims
quantitatifs (factuel_quantitatif) → Le Compteur. La source est polymorphe
(post X ou article presse). Le `verbatim` exact est toujours conservé (fidélité).
"""

from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base, TimestampMixin


class Claim(Base, TimestampMixin):
    __tablename__ = "claims"

    id: Mapped[int] = mapped_column(primary_key=True)

    # Source polymorphe
    platform: Mapped[str] = mapped_column(String(10))  # x | press
    post_id: Mapped[int | None] = mapped_column(
        ForeignKey("posts.id", ondelete="CASCADE"), index=True
    )
    article_id: Mapped[int | None] = mapped_column(
        ForeignKey("articles.id", ondelete="CASCADE"), index=True
    )

    # Locuteur
    personality_id: Mapped[int | None] = mapped_column(
        ForeignKey("personalities.id", ondelete="SET NULL"), index=True
    )
    speaker_name: Mapped[str | None] = mapped_column(String(200))
    party: Mapped[str | None] = mapped_column(String(60))

    # Contenu (fidélité au verbatim)
    verbatim: Mapped[str] = mapped_column(Text, nullable=False)
    # « direct » : le verbatim est entre guillemets DANS le document, ce sont les
    # mots du locuteur. « rapporte » : c'est la formulation du journaliste. La
    # une affichait les deux entre guillemets sous le nom de la personne, ce qui
    # lui prêtait des phrases qu'elle n'avait pas prononcées. Voir
    # `services/analysis/quotation.py`. `None` = pas encore établi.
    quote_style: Mapped[str | None] = mapped_column(String(10), index=True)
    # Une phrase dite une fois et reprise par vingt journaux reste une phrase.
    # `duplicate_of` pointe la prise de position reprise ; `n_reprises` la porte,
    # parce que la reprise est un signal de poids, pas du bruit. Voir
    # `services/analysis/redites.py`. `None` = c'est l'original.
    duplicate_of: Mapped[int | None] = mapped_column(
        ForeignKey("claims.id", ondelete="SET NULL"), index=True)
    n_reprises: Mapped[int | None] = mapped_column(Integer, default=0)
    canonical: Mapped[str | None] = mapped_column(Text)
    claim_type: Mapped[str] = mapped_column(String(30), default="factuel_quantitatif")

    # Rattachement thématique + référent (clé de comparaison / blocking)
    theme: Mapped[str | None] = mapped_column(String(40))
    subtheme: Mapped[str | None] = mapped_column(String(60))
    # Grille CAP (Comparative Agendas Project) — voir services/analysis/cap.py.
    # Remplace la grille maison, qui avait dérivé à 24 valeurs et n'était
    # comparable à rien. `theme` reste le temps de la bascule : l'entonnoir et
    # trois pages le lisent encore.
    cap_major: Mapped[int | None] = mapped_column(Integer, index=True)
    cap_subtopic: Mapped[int | None] = mapped_column(Integer)
    # La signature complete du codeur, pas le seul numero de grille :
    # « cap-major-2019/2q-v1/<modele>@t0.0 ». Les noms de modeles sont longs,
    # et une colonne trop courte ne se voit pas en SQLite — elle casse en
    # Postgres, a chaque passe.
    cap_version: Mapped[str | None] = mapped_column(String(120))

    # ── Engagement (méthode Polimètre, cf. services/analysis/pledges.py) ──
    # Un engagement EST une déclaration : lui donner sa table ferait deux
    # objets pour une même phrase, à tenir synchronisés pour rien. Trois
    # colonnes suffisent — et `pledge_version` est large, on a déjà payé une
    # fois le prix d'une colonne trop courte visible en production seulement.
    pledge_version: Mapped[str | None] = mapped_column(String(120))
    pledge_measure: Mapped[str | None] = mapped_column(String(400))
    pledge_status: Mapped[str | None] = mapped_column(String(24), index=True)

    # ── Pertinence (cf. services/analysis/relevance.py) ──────────────────
    # Dérivé, recalculé à chaque passe. `relevance_why` porte les raisons en
    # clair : un classement dont on ne peut pas dire le pourquoi est une boîte
    # noire, et la page doit pouvoir l'écrire à côté de la déclaration.
    relevance: Mapped[float | None] = mapped_column(Float, index=True)
    relevance_why: Mapped[list | None] = mapped_column(JSON)
    referent_key: Mapped[str | None] = mapped_column(
        ForeignKey("referents.key", ondelete="SET NULL"), index=True
    )

    # Quantité (pour Le Compteur)
    qty_value: Mapped[float | None] = mapped_column(Float)
    qty_unit: Mapped[str | None] = mapped_column(String(60))
    qty_unit_kind: Mapped[str | None] = mapped_column(String(30))
    qty_horizon: Mapped[str | None] = mapped_column(String(30))
    qty_modality: Mapped[str | None] = mapped_column(String(20))

    stance_polarity: Mapped[str | None] = mapped_column(String(20))
    # OBJET de la prise de position (« l'âge de départ à la retraite »,
    # « l'aide militaire à l'Ukraine »). Le LLM le produit à chaque extraction ;
    # il n'était pas stocké. C'est pourtant LE sujet : sans lui, on ne pouvait
    # comparer que par thème (15 rayons), granularité à laquelle deux propos
    # n'ont rien à voir. Sert de signature primaire au regroupement en sujets.
    stance_target: Mapped[str | None] = mapped_column(String(300), index=True)
    # Sujet auquel la déclaration appartient — l'unité DANS LAQUELLE deux propos
    # se confrontent utilement (cf. models/subject.py).
    subject_id: Mapped[int | None] = mapped_column(
        ForeignKey("subjects.id", ondelete="SET NULL"), index=True
    )

    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Provenance de l'extraction
    extraction_method: Mapped[str] = mapped_column(String(20), default="deterministic")
    extraction_model: Mapped[str | None] = mapped_column(String(60))
    confidence: Mapped[float] = mapped_column(Float, default=0.5)
    human_validated: Mapped[bool] = mapped_column(Boolean, default=False)

    # Dédup : une assertion (source, référent, valeur) ne doit exister qu'une fois.
    dedup_key: Mapped[str] = mapped_column(String(64), unique=True, index=True)

    # Embedding sémantique (A0) — blocking/near-dup par cosinus en mémoire à
    # l'échelle actuelle ; deviendra VECTOR(1024)+pgvector sans changer la logique
    # (même décision que Referent.embedding, cf services/analysis/embeddings.py).
    embedding: Mapped[list | None] = mapped_column(JSON)

    __table_args__ = (
        Index("ix_claims_referent_published", "referent_key", "published_at"),
    )
