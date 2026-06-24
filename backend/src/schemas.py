"""Pydantic response models."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class PersonalityOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    full_name: str
    handle: str | None
    group_code: str
    group_long: str | None
    famille: str | None
    role: str | None
    verif: str | None
    circo: str | None
    departement: str | None
    photo_url: str | None
    is_active: bool


class PersonalityMini(BaseModel):
    """Auteur enrichi pour le flux de veille (métadonnées soignées)."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    full_name: str
    handle: str | None
    group_code: str
    group_long: str | None = None
    famille: str | None = None
    role: str | None = None
    verif: str | None = None
    circo: str | None = None
    departement: str | None = None
    photo_url: str | None


class FeedItem(BaseModel):
    """A post enriched with its author, for the feed UI."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    url: str
    content: str
    published_at: datetime | None
    is_retweet: bool
    is_reply: bool
    media_url: str | None
    likes: int | None
    retweets: int | None
    replies: int | None
    quotes: int | None
    theme: str | None
    personality: PersonalityMini


class FeedPage(BaseModel):
    total: int
    limit: int
    offset: int
    items: list[FeedItem]


class CollectionStats(BaseModel):
    run_id: int
    personalities_polled: int
    posts_new: int
    errors: int
    instance_used: str | None


class ArticleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    media_source_id: str
    source_name: str | None = None
    leaning: str | None = None
    url: str
    title: str
    author: str | None
    published_at: datetime | None
    matched_keywords: list | None
    matched_personalities: list | None
    is_statement: bool
    nature: str | None = None
    snapshot_url: str | None
    archived_at: datetime | None
    theme: str | None
    word_count: int


class ArticleDetail(ArticleOut):
    """Article complet (avec le texte) pour le panneau de lecture."""

    content: str


class ArticlePage(BaseModel):
    total: int
    limit: int
    offset: int
    items: list[ArticleOut]


class ClaimMini(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    platform: str
    qty_value: float | None
    qty_unit: str | None
    speaker_name: str | None
    party: str | None
    published_at: datetime | None
    verbatim: str
    canonical: str | None
    confidence: float
    source_url: str | None = None


class ContradictionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    type: int
    score: float
    status: str
    rationale: str | None
    referent_key: str | None
    validator: str | None
    detected_at: datetime
    claim_a: ClaimMini
    claim_b: ClaimMini


class ContradictionPage(BaseModel):
    total: int
    limit: int
    offset: int
    items: list[ContradictionOut]
