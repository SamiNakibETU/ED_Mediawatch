"""French-press collector via RSS, adapted from breve_de_presse_PMO's RSSCollector.

Pipeline per source: fetch RSS → for each entry, lexical relevance pass on
title+summary → if it concerns the RN/affiliés, extract full text (trafilatura)
→ store Article with matched keywords/personalities. Per-domain rate limiting,
concurrency cap, idempotent dedupe by url hash — same proven shape as the PMO.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import aiohttp
import feedparser
import structlog
from sqlalchemy import select

from src.config import get_settings
from src.database import get_session_factory
from src.models.article import Article
from src.models.collection_run import CollectionRun
from src.models.media_source import MediaSource
from src.models.personality import Personality
from src.services.collection.extractor_client import extract_fulltext
from src.services.collection.relevance import assess
from src.utils import clean_html, feed_datetime, sha256

logger = structlog.get_logger(__name__)
settings = get_settings()


# Last-name tokens too ambiguous to match on their own (places, party words…).
_SURNAME_STOPLIST = {
    "national", "republique", "paris", "loir", "france", "realpolitik",
    "assemblee", "groupe", "udr", "rn",
}


def _surnames(personalities: list[Personality]) -> set[str]:
    out: set[str] = set()
    for p in personalities:
        # Party / group accounts aren't people — skip their "surnames".
        if (p.famille or "").lower() in {"officiel", "groupe"}:
            continue
        parts = p.full_name.split()
        if not parts:
            continue
        last = parts[-1]
        if last.lower() in _SURNAME_STOPLIST:
            continue
        out.add(last)
        if len(parts) >= 2 and parts[-2].lower() in {"le", "de", "van", "du"}:
            out.add(" ".join(parts[-2:]))  # compound: "Le Pen", "de Lesquen"
    return out


class PressCollector:
    def __init__(self) -> None:
        self._factory = get_session_factory()
        self._sem = asyncio.Semaphore(settings.max_concurrent_requests)
        self._surnames: set[str] = set()

    async def collect_all(self) -> dict:
        async with self._factory() as db:
            sources = list(
                (
                    await db.execute(
                        select(MediaSource).where(MediaSource.is_active.is_(True))
                    )
                ).scalars().all()
            )
            personalities = list(
                (await db.execute(select(Personality))).scalars().all()
            )
        self._surnames = _surnames(personalities)

        logger.info("press.start", sources=len(sources))
        results = await asyncio.gather(
            *(self._collect_source(s) for s in sources), return_exceptions=True
        )

        stats = {"sources": len(sources), "articles_new": 0, "scanned": 0,
                 "errors": [], "per_source": {}}
        for src, res in zip(sources, results):
            if isinstance(res, Exception):
                stats["errors"].append({"source": src.id, "error": str(res)[:160]})
                logger.warning("press.source_error", source=src.id, error=str(res)[:160])
            else:
                stats["articles_new"] += res["new"]
                stats["scanned"] += res["scanned"]
                stats["per_source"][src.id] = res
        logger.info("press.complete", articles_new=stats["articles_new"])
        return stats

    async def _collect_source(self, source: MediaSource) -> dict:
        async with self._sem:
            headers = {"User-Agent": settings.user_agent,
                       "Accept": "application/rss+xml, application/xml, text/xml, */*"}
            try:
                async with aiohttp.ClientSession(headers=headers) as http:
                    async with http.get(
                        source.rss_url,
                        timeout=aiohttp.ClientTimeout(total=settings.request_timeout_seconds),
                        allow_redirects=True,
                    ) as resp:
                        if resp.status != 200:
                            return {"new": 0, "scanned": 0, "status": resp.status}
                        content = await resp.text()
            except Exception as exc:  # noqa: BLE001
                return {"new": 0, "scanned": 0, "error": str(exc)[:120]}

            feed = feedparser.parse(content)
            if feed.bozo and not feed.entries:
                return {"new": 0, "scanned": 0, "bozo": True}

            new = scanned = 0
            async with self._factory() as db:
                for entry in feed.entries[:60]:
                    scanned += 1
                    url = getattr(entry, "link", None)
                    if not url:
                        continue
                    title = clean_html(getattr(entry, "title", ""))
                    summary = clean_html(getattr(entry, "summary", "") if hasattr(entry, "get") else "")
                    verdict = assess(f"{title} {summary}", self._surnames)
                    if not verdict["relevant"]:
                        continue

                    h = sha256(url)
                    with db.no_autoflush:
                        exists = (
                            await db.execute(
                                select(Article.id).where(Article.url_hash == h)
                            )
                        ).scalar_one_or_none()
                    if exists:
                        continue

                    body = await extract_fulltext(url) or summary or title
                    # Re-assess on full body to refine statement detection.
                    full_verdict = assess(f"{title} {body}", self._surnames)

                    db.add(Article(
                        media_source_id=source.id,
                        url=url,
                        url_hash=h,
                        title=title or "(sans titre)",
                        content=body,
                        author=clean_html(getattr(entry, "author", "")) or None,
                        published_at=feed_datetime(entry),
                        matched_keywords=full_verdict["keywords"],
                        matched_personalities=full_verdict["personalities"],
                        is_statement=full_verdict["is_statement"],
                        word_count=len(body.split()),
                    ))
                    new += 1

                if new:
                    src = await db.get(MediaSource, source.id)
                    if src:
                        src.last_collected_at = datetime.now(timezone.utc)
                await db.commit()

            logger.info("press.source_done", source=source.id, new=new, scanned=scanned)
            return {"new": new, "scanned": scanned}


async def run_press_collection() -> dict:
    collector = PressCollector()
    factory = get_session_factory()
    async with factory() as db:
        run = CollectionRun(status="running", notes="press")
        db.add(run)
        await db.commit()
        await db.refresh(run)
        run_id = run.id

    stats = await collector.collect_all()

    async with factory() as db:
        run = await db.get(CollectionRun, run_id)
        if run:
            run.status = "completed"
            run.completed_at = datetime.now(timezone.utc)
            run.posts_new = stats["articles_new"]
            run.personalities_polled = stats["sources"]
            run.errors = len(stats["errors"])
            run.notes = "press"
            await db.commit()
    stats["run_id"] = run_id
    return stats
