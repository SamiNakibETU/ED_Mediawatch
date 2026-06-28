"""A press article that mentions / reports a far-right (RN & affiliés) statement.

Same analytical fields as Post (theme/subtheme) so X posts and press articles
flow through one classification + inconsistency-detection pipeline later.
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
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.models.base import Base, TimestampMixin


class Article(Base, TimestampMixin):
    __tablename__ = "articles"

    id: Mapped[int] = mapped_column(primary_key=True)

    media_source_id: Mapped[str] = mapped_column(
        ForeignKey("media_sources.id", ondelete="CASCADE"), index=True
    )
    media_source: Mapped["MediaSource"] = relationship(  # noqa: F821
        back_populates="articles"
    )

    url: Mapped[str] = mapped_column(String(700), nullable=False)
    url_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)

    title: Mapped[str] = mapped_column(String(600), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    author: Mapped[str | None] = mapped_column(String(200))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # `published_at` n'est jamais NULL en pratique : si le flux ne date pas
    # l'entrée, on retombe sur l'heure de collecte ET on lève ce drapeau pour ne
    # pas polluer l'axe temporel longitudinal (C0).
    published_estimated: Mapped[bool] = mapped_column(Boolean, default=False)

    # --- Qualité d'extraction (C0) — alimenté par le scraper-service v2 ---
    # Stratégie gagnante : curl_cffi | googlebot_referer | archive_ph |
    # playwright_stealth | jina_ai | wayback | llm_cleanup | rss_full | cookies…
    extraction_method: Mapped[str | None] = mapped_column(String(24))
    # `content` est-il l'article INTÉGRAL (vs chapô tronqué / page paywall) ?
    is_full_text: Mapped[bool | None] = mapped_column(Boolean)
    # Un marqueur de mur payant a-t-il été détecté dans le texte ?
    paywalled: Mapped[bool | None] = mapped_column(Boolean)
    # Score de complétude/qualité rendu par le scraper-service (0..1).
    confidence_score: Mapped[float | None] = mapped_column(Float)
    # Langue détectée (défaut fonctionnel 'fr').
    lang: Mapped[str | None] = mapped_column(String(8))
    # Rubrique/section si le flux la fournit.
    section: Mapped[str | None] = mapped_column(String(80))

    # Relevance: which far-right keywords / personalities the text matched.
    matched_keywords: Mapped[list | None] = mapped_column(JSON)
    matched_personalities: Mapped[list | None] = mapped_column(JSON)
    # True when the article reports an actual RN/affiliés statement (vs a mere mention).
    is_statement: Mapped[bool] = mapped_column(Boolean, default=False)
    # Nature de l'item : 'prise_de_parole' (figure ED s'exprime) | 'mention'.
    nature: Mapped[str | None] = mapped_column(String(20), index=True)

    # Archivage / reçus — preuve traçable même si l'article est supprimé/paywallé.
    snapshot_path: Mapped[str | None] = mapped_column(String(400))  # HTML local
    snapshot_url: Mapped[str | None] = mapped_column(String(700))   # Wayback/ArchiveBox
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Analytical phase (shared with Post)
    theme: Mapped[str | None] = mapped_column(String(60))
    subtheme: Mapped[str | None] = mapped_column(String(120))
    word_count: Mapped[int] = mapped_column(Integer, default=0)

    __table_args__ = (
        Index("ix_articles_source_published", "media_source_id", "published_at"),
        Index("ix_articles_theme", "theme"),
    )

    def __repr__(self) -> str:
        return f"<Article {self.url_hash[:8]} {self.title[:40]!r}>"
