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


_MIN_LEN = 350  # en-deçà : on considère le texte tronqué et on tente la suite

_BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
}


def _extract(html: str, *, recall: bool) -> str | None:
    return trafilatura.extract(
        html,
        include_comments=False,
        include_tables=False,
        favor_recall=recall,
        favor_precision=not recall,
        deduplicate=True,
        output_format="txt",
    )


async def _via_trafilatura(url: str) -> str | None:
    """Cascade façon PMO : recall → precision → fetch direct (UA navigateur)."""
    if trafilatura is None:
        return None
    best: str | None = None
    try:
        downloaded = await asyncio.to_thread(trafilatura.fetch_url, url)
        if downloaded:
            for recall in (True, False):
                txt = await asyncio.to_thread(_extract, downloaded, recall=recall)
                if txt and len(txt) > len(best or ""):
                    best = txt
                if best and len(best) >= _MIN_LEN:
                    return best
    except Exception as exc:  # noqa: BLE001
        logger.debug("extractor.trafilatura_fail", url=url, error=str(exc)[:120])

    # Repli : certains sites refusent le fetch trafilatura (UA), pas un vrai navigateur.
    if best is None or len(best) < _MIN_LEN:
        try:
            async with aiohttp.ClientSession(headers=_BROWSER_HEADERS) as http:
                async with http.get(
                    url, timeout=aiohttp.ClientTimeout(total=30), allow_redirects=True
                ) as resp:
                    if resp.status == 200:
                        html = await resp.text()
                        if html and len(html) > 500:
                            txt = await asyncio.to_thread(_extract, html, recall=True)
                            if txt and len(txt) > len(best or ""):
                                best = txt
        except Exception as exc:  # noqa: BLE001
            logger.debug("extractor.direct_fetch_fail", url=url, error=str(exc)[:120])

    return best


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
