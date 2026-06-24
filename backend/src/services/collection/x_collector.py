"""X/Twitter collector via Nitter RSS.

For each active personality with a handle, fetch their Nitter RSS timeline,
parse tweets with feedparser, dedupe by tweet id, and persist new Posts.
Mirrors the proven RSS-collector pattern from breve_de_presse_PMO
(rate-limited, concurrent, idempotent), pointed at Nitter instead of newspapers.
"""

from __future__ import annotations

import asyncio
import re
from datetime import datetime, timezone

import feedparser
import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import get_settings
from src.database import get_session_factory
from src.models.collection_run import CollectionRun
from src.models.personality import Personality
from src.models.post import Post
from src.services.collection.nitter_client import NitterClient
from src.services.collection.x_html_parser import parse_profile_html
from src.utils import clean_html, feed_datetime, tweet_guid
from src.vocabulary import RunKind, RunStatus, Source

logger = structlog.get_logger(__name__)

_IMG_RE = re.compile(r'<img[^>]+src="([^"]+)"', re.IGNORECASE)


def _extract_media(entry) -> str | None:
    summary = entry.get("summary", "") if hasattr(entry, "get") else ""
    m = _IMG_RE.search(summary or "")
    return m.group(1) if m else None


def parse_feed(xml: str, handle: str) -> list[dict]:
    """Parse a Nitter RSS document into normalized post dicts."""
    feed = feedparser.parse(xml)
    out: list[dict] = []
    for entry in feed.entries:
        link = getattr(entry, "link", "") or ""
        title = getattr(entry, "title", "") or ""
        creator = (getattr(entry, "author", "") or "").lstrip("@")

        is_retweet = title.startswith("RT by ") or (
            bool(creator) and creator.lower() != handle.lower()
        )
        is_reply = title.startswith("R to ")

        content = clean_html(title)
        if not content:
            continue
        out.append(
            {
                "guid": tweet_guid(handle, link),
                "url": link,
                "content": content,
                "published_at": feed_datetime(entry),
                "is_retweet": is_retweet,
                "is_reply": is_reply,
                "media_url": _extract_media(entry),
                "word_count": len(content.split()),
            }
        )
    return out


def _post_conflict_insert(rows: list[dict]):
    """INSERT … ON CONFLICT(guid) DO NOTHING — dialecte SQLite ou PostgreSQL.

    Évite qu'un guid en double (collecte concurrente : startup vs scheduler, ou
    réplay) ne fasse échouer le commit et perdre TOUT le lot. Idempotent par
    nature. `insert().values(rows)` produit un seul INSERT multi-VALUES → un
    rowcount fiable (= lignes réellement insérées, conflits exclus)."""
    if get_settings().database_url.startswith("postgres"):
        from sqlalchemy.dialects.postgresql import insert as _insert
    else:
        from sqlalchemy.dialects.sqlite import insert as _insert
    return _insert(Post).values(rows).on_conflict_do_nothing(index_elements=["guid"])


async def _insert_new(db: AsyncSession, personality_id: int, posts: list[dict]) -> int:
    """Insert new posts, deduped by guid via ON CONFLICT. RSS or HTML dicts."""
    if not posts:
        return 0
    now = datetime.now(timezone.utc)
    rows: list[dict] = []
    for pd in posts:
        data = dict(pd)
        data["personality_id"] = personality_id
        data["source"] = Source.X
        # engagement present (HTML path) → timestamp it
        if data.get("likes") is not None or data.get("retweets") is not None:
            data["engagement_captured_at"] = now
        rows.append(data)
    result = await db.execute(_post_conflict_insert(rows))
    await db.commit()
    return result.rowcount or 0


async def _collect_one(
    client: NitterClient, db: AsyncSession, p: Personality
) -> tuple[int, str | None]:
    """Live RSS collection (no engagement; works on public nitter.net)."""
    if not p.handle:
        return 0, None
    xml, instance = await client.fetch_rss(p.handle)
    if not xml:
        return 0, instance
    posts = parse_feed(xml, p.handle)
    new_count = await _insert_new(db, p.id, posts)
    logger.info("collect.personality", handle=p.handle, new=new_count, instance=instance)
    return new_count, instance


async def collect_one_html(
    client: NitterClient,
    db: AsyncSession,
    p: Personality,
    *,
    max_pages: int = 1,
    since: datetime | None = None,
) -> tuple[int, str | None]:
    """HTML collection WITH engagement, paginated by cursor (backfill-capable).

    Walks profile pages following the `?cursor=` link until `max_pages`, or until
    posts predate `since` (backfill cutoff), or no further cursor. Requires an
    instance that serves the timeline (self-hosted Nitter in practice).
    """
    if not p.handle:
        return 0, None
    path = f"/{p.handle}"
    last_instance: str | None = None
    total_new = 0

    for _ in range(max_pages):
        html, instance = await client.fetch_html(path)
        if not html:
            break
        last_instance = instance
        posts, cursor = parse_profile_html(html, p.handle, base_url=instance)
        if not posts:
            break

        if since is not None:
            kept = [pd for pd in posts if not pd["published_at"] or pd["published_at"] >= since]
            reached_cutoff = len(kept) < len(posts)
            posts = kept
        else:
            reached_cutoff = False

        total_new += await _insert_new(db, p.id, posts)

        if reached_cutoff or not cursor:
            break
        path = f"/{p.handle}{cursor if cursor.startswith('?') else '?' + cursor}"

    logger.info("collect.html", handle=p.handle, new=total_new, instance=last_instance)
    return total_new, last_instance


async def run_backfill(since: datetime, max_pages_per_handle: int = 40) -> dict:
    """Backfill every active handle back to `since` via HTML pagination.

    Resumable: dedup by guid means re-runs only fetch what's missing.
    """
    factory = get_session_factory()
    client = NitterClient()
    async with factory() as db:
        personalities = list(
            (
                await db.execute(
                    select(Personality).where(
                        Personality.is_active.is_(True),
                        Personality.handle.isnot(None),
                    )
                )
            ).scalars().all()
        )

    logger.info("backfill.start", handles=len(personalities),
                since=since.isoformat(), max_pages=max_pages_per_handle)
    total_new = blocked = 0
    for p in personalities:
        async with factory() as db:
            try:
                new, inst = await collect_one_html(
                    client, db, p, max_pages=max_pages_per_handle, since=since
                )
                total_new += new
                if inst is None:
                    blocked += 1
            except Exception as exc:  # noqa: BLE001
                logger.warning("backfill.error", handle=p.handle, error=str(exc)[:160])
    stats = {"handles": len(personalities), "posts_new": total_new, "blocked": blocked,
             "since": since.isoformat()}
    logger.info("backfill.complete", **stats)
    return stats


async def run_collection(use_html: bool | None = None) -> dict:
    """One full sweep over the active pool. Returns summary stats.

    Uses HTML (with engagement) when a self-hosted Nitter is configured,
    else RSS (no engagement). Override with `use_html`.
    """
    factory = get_session_factory()
    client = NitterClient()
    if use_html is None:
        use_html = bool(get_settings().nitter_self_hosted.strip())

    async with factory() as db:
        result = await db.execute(
            select(Personality).where(
                Personality.is_active.is_(True),
                Personality.handle.isnot(None),
            )
        )
        personalities = list(result.scalars().all())

        run = CollectionRun(
            kind=RunKind.X,
            status=RunStatus.RUNNING,
            personalities_polled=len(personalities),
        )
        db.add(run)
        await db.commit()
        await db.refresh(run)
        run_id = run.id

    logger.info("collection.start", personalities=len(personalities))

    total_new = 0
    errors = 0
    instance_used: str | None = None

    async def worker(p: Personality) -> None:
        nonlocal total_new, errors, instance_used
        async with factory() as db:
            try:
                if use_html:
                    new, inst = await collect_one_html(client, db, p, max_pages=1)
                else:
                    new, inst = await _collect_one(client, db, p)
                total_new += new
                if inst:
                    instance_used = inst
            except Exception as exc:  # noqa: BLE001
                errors += 1
                logger.warning("collect.error", handle=p.handle, error=str(exc)[:160])

    # Bounded concurrency is enforced inside NitterClient via its semaphore.
    await asyncio.gather(*(worker(p) for p in personalities))

    async with factory() as db:
        run = await db.get(CollectionRun, run_id)
        if run:
            run.status = RunStatus.COMPLETED
            run.completed_at = datetime.now(timezone.utc)
            run.posts_new = total_new
            run.errors = errors
            run.instance_used = instance_used
            await db.commit()

    stats = {
        "run_id": run_id,
        "personalities_polled": len(personalities),
        "posts_new": total_new,
        "errors": errors,
        "instance_used": instance_used,
    }
    logger.info("collection.complete", **stats)
    return stats
