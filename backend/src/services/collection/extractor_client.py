"""Pluggable full-text extractor.

Default (local-first): trafilatura. Production: the v2/media-watch
`scraper-service` (anti-paywall cascade: curl_cffi → Playwright Stealth →
Scrapling → Jina → Wayback). Set EXTRACTOR_URL to route through it; the press
collector code stays unchanged.
"""

from __future__ import annotations

import asyncio

import aiohttp
import structlog

from src.config import get_settings

logger = structlog.get_logger(__name__)

try:
    import trafilatura
except Exception:  # noqa: BLE001
    trafilatura = None


async def _via_service(url: str, base: str, timeout: int) -> str | None:
    payload = {"url": url, "force_complete": True}
    try:
        async with aiohttp.ClientSession() as http:
            async with http.post(
                f"{base.rstrip('/')}/extract",
                json=payload,
                timeout=aiohttp.ClientTimeout(total=timeout),
            ) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json()
                # scraper-service returns {"content": "...", ...}
                return data.get("content") or data.get("text")
    except Exception as exc:  # noqa: BLE001
        logger.debug("extractor.service_fail", url=url, error=str(exc)[:120])
        return None


async def _via_trafilatura(url: str) -> str | None:
    if trafilatura is None:
        return None
    try:
        downloaded = await asyncio.to_thread(trafilatura.fetch_url, url)
        if not downloaded:
            return None
        return await asyncio.to_thread(
            trafilatura.extract,
            downloaded,
            include_comments=False,
            include_tables=False,
            favor_recall=True,
            output_format="txt",
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("extractor.trafilatura_fail", url=url, error=str(exc)[:120])
        return None


async def extract_fulltext(url: str) -> str | None:
    """Return clean article text, via the scraper-service when configured."""
    settings = get_settings()
    if settings.extractor_url.strip():
        text = await _via_service(
            url, settings.extractor_url, settings.request_timeout_seconds * 4
        )
        if text:
            return text
        # fall through to local extraction if the service missed
    return await _via_trafilatura(url)
