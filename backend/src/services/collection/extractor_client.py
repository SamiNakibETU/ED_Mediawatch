"""Pluggable full-text extractor.

Default (local-first): trafilatura. Production: the v2/media-watch
`scraper-service` (anti-paywall cascade: curl_cffi → Playwright Stealth →
Scrapling → Jina → Wayback). Set EXTRACTOR_URL to route through it; the press
collector code stays unchanged.
"""

from __future__ import annotations

import asyncio
import re

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


def _browser_headers() -> dict:
    """En-têtes « vrai navigateur » (UA = source unique settings.user_agent)."""
    return {
        "User-Agent": get_settings().user_agent,
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


async def extract_html(html: str | None) -> str | None:
    """Texte d'article propre depuis un HTML déjà en main (ex. `content:encoded`
    du flux RSS, qui contient souvent l'article complet → pas de scraping)."""
    if trafilatura is None or not html:
        return None
    best: str | None = None
    for recall in (True, False):
        try:
            txt = await asyncio.to_thread(_extract, html, recall=recall)
        except Exception:  # noqa: BLE001
            txt = None
        if txt and len(txt) > len(best or ""):
            best = txt
        if best and len(best) >= _MIN_LEN:
            break
    return best


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
            async with aiohttp.ClientSession(headers=_browser_headers()) as http:
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


_MD_LINK_RE = re.compile(r"\[([^\]]*)\]\([^)]*\)")  # [texte](url) → texte


async def _via_jina(url: str, timeout: int) -> str | None:
    """Jina Reader (r.jina.ai) : texte propre rendu JS, récupéré depuis les IP de
    Jina → contourne l'IP datacenter blacklistée et les paywalls souples."""
    base = get_settings().jina_reader_url.rstrip("/")
    try:
        async with aiohttp.ClientSession(headers={"Accept": "text/plain"}) as http:
            async with http.get(
                f"{base}/{url}", timeout=aiohttp.ClientTimeout(total=timeout)
            ) as resp:
                if resp.status != 200:
                    return None
                md = await resp.text()
    except Exception as exc:  # noqa: BLE001
        logger.debug("extractor.jina_fail", url=url, error=str(exc)[:120])
        return None
    if "Markdown Content:" in md:
        md = md.split("Markdown Content:", 1)[1]
    md = _MD_LINK_RE.sub(r"\1", md)            # déréférence les liens markdown
    md = re.sub(r"\n{3,}", "\n\n", md).strip()
    return md or None


async def extract_fulltext(url: str) -> str | None:
    """Texte d'article propre via une cascade anti-blocage, meilleur candidat retenu.

    Ordre : scraper-service PMO (EXTRACTOR_URL) → trafilatura (local) → Jina Reader.
    On s'arrête au premier résultat « complet » (≥ _MIN_LEN) ; sinon on garde le
    plus long. Jina sert de débloqueur (IP tierces) quand le fetch local échoue
    (403 IP datacenter, rendu JS, paywall souple).
    """
    settings = get_settings()
    t = settings.request_timeout_seconds
    best: str | None = None

    async def consider(text: str | None) -> bool:
        nonlocal best
        if text and len(text) > len(best or ""):
            best = text
        return bool(best and len(best) >= _MIN_LEN)

    if settings.extractor_url.strip():
        if await consider(await _via_service(url, settings.extractor_url, t * 4)):
            return best
    if await consider(await _via_trafilatura(url)):
        return best
    if settings.jina_reader_enabled:
        if await consider(await _via_jina(url, t * 2)):
            return best
    return best
