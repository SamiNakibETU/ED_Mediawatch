"""Resilient Nitter client.

Nitter public instances are individually flaky (rotating Cloudflare / Anubis
bot challenges, 302s, rate limits) — see the original project's
DIAGNOSTIC_NITTER_DOWN.md. Strategy here:

  * Keep an ordered list of candidate instances (self-hosted first if set).
  * For each request, try instances in order; an instance that returns a real
    RSS document wins and is remembered as "preferred" for subsequent calls.
  * Detect bot-challenge / redirect HTML and transparently fall back.
  * Per-instance rate limiting + global concurrency cap to stay polite.

This keeps the public-instance path working for the local-first slice while the
recommended production path (self-hosting Nitter, set NITTER_SELF_HOSTED) drops
in by changing one env var.
"""

from __future__ import annotations

import asyncio
import time

import aiohttp
import structlog

from src.config import get_settings

logger = structlog.get_logger(__name__)


def _looks_like_rss(text: str) -> bool:
    head = text[:400].lstrip().lower()
    return head.startswith("<?xml") and "<rss" in text[:2000].lower()


def _looks_like_timeline(text: str) -> bool:
    # A real Nitter profile page; not a bot-challenge / empty body.
    return "timeline-item" in text and len(text) > 2000


class NitterClient:
    def __init__(self) -> None:
        s = get_settings()
        self._instances: list[str] = s.nitter_instance_list
        self._preferred: str | None = self._instances[0] if self._instances else None
        self._delay = s.request_delay_seconds
        self._timeout = s.request_timeout_seconds
        self._ua = s.user_agent
        self._sem = asyncio.Semaphore(s.max_concurrent_requests)
        self._last_hit: dict[str, float] = {}

    def _ordered(self) -> list[str]:
        """Preferred instance first, then the rest."""
        if self._preferred and self._preferred in self._instances:
            return [self._preferred] + [i for i in self._instances if i != self._preferred]
        return list(self._instances)

    async def _rate_limit(self, instance: str) -> None:
        last = self._last_hit.get(instance, 0.0)
        wait = self._delay - (time.monotonic() - last)
        if wait > 0:
            await asyncio.sleep(wait)
        self._last_hit[instance] = time.monotonic()

    async def fetch_rss(self, handle: str) -> tuple[str | None, str | None]:
        """Return (rss_xml, instance_used) trying instances until one works."""
        headers = {
            "User-Agent": self._ua,
            "Accept": "application/rss+xml, application/xml, text/xml, */*",
            "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
        }
        async with self._sem:
            async with aiohttp.ClientSession(headers=headers) as http:
                for instance in self._ordered():
                    url = f"{instance}/{handle}/rss"
                    await self._rate_limit(instance)
                    try:
                        async with http.get(
                            url,
                            timeout=aiohttp.ClientTimeout(total=self._timeout),
                            allow_redirects=False,
                        ) as resp:
                            if resp.status != 200:
                                logger.debug(
                                    "nitter.skip", instance=instance,
                                    handle=handle, status=resp.status,
                                )
                                continue
                            text = await resp.text()
                    except Exception as exc:  # noqa: BLE001
                        logger.debug(
                            "nitter.error", instance=instance,
                            handle=handle, error=str(exc)[:120],
                        )
                        continue

                    if not _looks_like_rss(text):
                        logger.debug(
                            "nitter.not_rss", instance=instance, handle=handle
                        )
                        continue

                    self._preferred = instance
                    return text, instance

        logger.warning("nitter.all_failed", handle=handle)
        return None, None

    async def fetch_html(self, path: str) -> tuple[str | None, str | None]:
        """Fetch a Nitter HTML page (profile or ?cursor=…) with rotation.

        Returns (html, instance_base). Needs an instance that actually serves the
        timeline (public ones are usually challenge-protected → self-host).
        `path` starts with '/', e.g. '/J_Bardella' or '/J_Bardella?cursor=ABC'.
        """
        headers = {
            "User-Agent": self._ua,
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
        }
        async with self._sem:
            async with aiohttp.ClientSession(headers=headers) as http:
                for instance in self._ordered():
                    url = f"{instance}{path}"
                    await self._rate_limit(instance)
                    try:
                        async with http.get(
                            url,
                            timeout=aiohttp.ClientTimeout(total=self._timeout),
                            allow_redirects=False,
                        ) as resp:
                            if resp.status != 200:
                                continue
                            text = await resp.text()
                    except Exception as exc:  # noqa: BLE001
                        logger.debug("nitter.html_error", instance=instance,
                                     path=path, error=str(exc)[:120])
                        continue
                    if not _looks_like_timeline(text):
                        logger.debug("nitter.html_blocked", instance=instance, path=path)
                        continue
                    self._preferred = instance
                    return text, instance
        return None, None
