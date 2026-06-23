"""A collected X/Twitter post (via Nitter RSS).

Schema is source-agnostic on purpose: a `source` column lets us add press
articles later into the same analytical pipeline (themes, inconsistencies).
"""

from datetime import datetime

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.models.base import Base, TimestampMixin


class Post(Base, TimestampMixin):
    __tablename__ = "posts"

    id: Mapped[int] = mapped_column(primary_key=True)

    personality_id: Mapped[int] = mapped_column(
        ForeignKey("personalities.id", ondelete="CASCADE"), index=True
    )
    personality: Mapped["Personality"] = relationship(  # noqa: F821
        back_populates="posts"
    )

    source: Mapped[str] = mapped_column(String(20), default="x", nullable=False)

    # Stable dedupe key: hash of the canonical post URL.
    guid: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    url: Mapped[str] = mapped_column(String(600), nullable=False)

    content: Mapped[str] = mapped_column(Text, nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Tweet typology
    is_retweet: Mapped[bool] = mapped_column(default=False)
    is_reply: Mapped[bool] = mapped_column(default=False)

    # Media + engagement (engagement requires Nitter HTML; filled in P0.5)
    media_url: Mapped[str | None] = mapped_column(String(600))
    likes: Mapped[int | None] = mapped_column(Integer)
    retweets: Mapped[int | None] = mapped_column(Integer)
    replies: Mapped[int | None] = mapped_column(Integer)
    quotes: Mapped[int | None] = mapped_column(Integer)
    engagement_captured_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )

    # Archivage / reçus
    snapshot_path: Mapped[str | None] = mapped_column(String(400))
    snapshot_url: Mapped[str | None] = mapped_column(String(700))
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Reserved for the analytical phase (theme classification, inconsistency).
    theme: Mapped[str | None] = mapped_column(String(60))
    subtheme: Mapped[str | None] = mapped_column(String(120))

    word_count: Mapped[int] = mapped_column(Integer, default=0)

    __table_args__ = (
        Index("ix_posts_personality_published", "personality_id", "published_at"),
        Index("ix_posts_theme", "theme"),
    )

    def __repr__(self) -> str:
        return f"<Post {self.guid} p={self.personality_id} {self.content[:40]!r}>"
