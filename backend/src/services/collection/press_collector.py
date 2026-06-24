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
from src.services.collection.extractor_client import extract_fulltext, extract_html
from src.services.collection.relevance import RelevanceIndex, build_index
from src.utils import clean_html, feed_datetime, sha256
from src.vocabulary import Nature, RunKind, RunStatus

logger = structlog.get_logger(__name__)
settings = get_settings()

# UA navigateur (source unique : settings.user_agent) — plusieurs flux RSS
# (Le Figaro, Le Télégramme…) renvoient 403 au UA par défaut mais 200 à un
# vrai navigateur.


def _rss_full_html(entry) -> str:
    """HTML de l'article complet quand le flux le fournit (content:encoded)."""
    content = getattr(entry, "content", None)
    if content:
        try:
            return content[0].get("value", "") or ""
        except Exception:  # noqa: BLE001
            return ""
    return ""


# content:encoded n'est traité comme texte INTÉGRAL que s'il est clairement un
# article complet (et pas juste un chapô). Seuil volontairement plus haut que
# extractor._MIN_LEN (350) : un texte RSS court est souvent un résumé, alors
# qu'un scrape ≥350 vise déjà le nœud <article>. En-deçà, on scrape pour comparer.
_RSS_FULLTEXT_MIN = 1200


class PressCollector:
    def __init__(self) -> None:
        self._factory = get_session_factory()
        self._sem = asyncio.Semaphore(settings.max_concurrent_requests)
        self._index: RelevanceIndex | None = None

    async def _resolve_body(self, entry, url: str, title: str, summary: str) -> str:
        """Meilleur texte d'article disponible.

        1) `content:encoded` du flux s'il constitue déjà l'article complet
           (≥ `_RSS_FULLTEXT_MIN`) → pas de scraping ;
        2) sinon on scrape et on garde le candidat le plus long parmi
           scrape / texte RSS propre / HTML RSS brut nettoyé / résumé / titre.
        """
        rss_html = _rss_full_html(entry)
        rss_text = await extract_html(rss_html)
        if rss_text and len(rss_text) >= _RSS_FULLTEXT_MIN:
            return rss_text
        scraped = await extract_fulltext(url)
        rss_raw = clean_html(rss_html) if rss_html else ""
        return max(
            (c for c in (scraped, rss_text, rss_raw, summary, title) if c),
            key=len,
            default=summary or title or "",
        )

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
        # Figures (personnes) suivies : on exclut les comptes parti/groupe, le
        # parti est déjà géré comme « speaker collectif » par l'index.
        people = [
            p.full_name for p in personalities
            if (p.famille or "").lower() not in {"officiel", "groupe"}
        ]
        self._index = build_index(people)

        logger.info("press.start", sources=len(sources))
        results = await asyncio.gather(
            *(self._collect_source(s) for s in sources), return_exceptions=True
        )

        stats = {"sources": len(sources), "articles_new": 0, "scanned": 0,
                 "mentions_skipped": 0, "errors": [], "per_source": {}}
        for src, res in zip(sources, results):
            if isinstance(res, Exception):
                stats["errors"].append({"source": src.id, "error": str(res)[:160]})
                logger.warning("press.source_error", source=src.id, error=str(res)[:160])
            else:
                stats["articles_new"] += res["new"]
                stats["scanned"] += res["scanned"]
                stats["mentions_skipped"] += res.get("mentions_skipped", 0)
                stats["per_source"][src.id] = res
        logger.info("press.complete", articles_new=stats["articles_new"],
                    mentions_skipped=stats["mentions_skipped"])
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

            new = scanned = mentions = 0
            async with self._factory() as db:
                for entry in feed.entries[:60]:
                    scanned += 1
                    url = getattr(entry, "link", None)
                    if not url:
                        continue
                    title = clean_html(getattr(entry, "title", ""))
                    summary = clean_html(getattr(entry, "summary", "") if hasattr(entry, "get") else "")
                    # Gate bon marché : le RN / une figure est-il seulement présent ?
                    if not self._index.assess(f"{title} {summary}")["relevant"]:
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

                    body = await self._resolve_body(entry, url, title, summary)
                    # Décision de NATURE sur le texte complet.
                    verdict = self._index.assess(f"{title}. {body}")
                    # Phase 1 : on ne garde QUE les prises de parole ED.
                    if verdict["nature"] != Nature.PRISE_DE_PAROLE:
                        mentions += 1
                        continue

                    db.add(Article(
                        media_source_id=source.id,
                        url=url,
                        url_hash=h,
                        title=title or "(sans titre)",
                        content=body,
                        author=clean_html(getattr(entry, "author", "")) or None,
                        published_at=feed_datetime(entry),
                        matched_keywords=verdict["keywords"],
                        matched_personalities=verdict["personalities"],
                        is_statement=True,
                        nature=Nature.PRISE_DE_PAROLE,
                        word_count=len(body.split()),
                    ))
                    new += 1

                if new:
                    src = await db.get(MediaSource, source.id)
                    if src:
                        src.last_collected_at = datetime.now(timezone.utc)
                await db.commit()

            logger.info("press.source_done", source=source.id, new=new,
                        scanned=scanned, mentions_skipped=mentions)
            return {"new": new, "scanned": scanned, "mentions_skipped": mentions}


async def run_press_collection(reset: bool = False) -> dict:
    collector = PressCollector()
    factory = get_session_factory()

    if reset:
        from sqlalchemy import delete

        async with factory() as db:
            await db.execute(delete(Article))
            await db.commit()
        logger.info("press.reset")

    async with factory() as db:
        run = CollectionRun(kind=RunKind.PRESS, status=RunStatus.RUNNING, notes="press")
        db.add(run)
        await db.commit()
        await db.refresh(run)
        run_id = run.id

    stats = await collector.collect_all()

    async with factory() as db:
        run = await db.get(CollectionRun, run_id)
        if run:
            run.status = RunStatus.COMPLETED
            run.completed_at = datetime.now(timezone.utc)
            run.posts_new = stats["articles_new"]
            run.personalities_polled = stats["sources"]
            run.errors = len(stats["errors"])
            run.notes = "press"
            await db.commit()
    stats["run_id"] = run_id
    return stats
