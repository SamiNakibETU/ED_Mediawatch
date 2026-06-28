"""Pluggable full-text extractor.

Default (local-first): trafilatura. Production: the v2/media-watch
`scraper-service` (anti-paywall cascade: curl_cffi → Playwright Stealth →
Scrapling → Jina → Wayback). Set EXTRACTOR_URL to route through it; the press
collector code stays unchanged.
"""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass
from functools import lru_cache
from urllib.parse import urlparse

import aiohttp
import structlog

from src.config import get_settings

logger = structlog.get_logger(__name__)

try:
    import trafilatura
except Exception:  # noqa: BLE001
    trafilatura = None


@dataclass
class Extraction:
    """Résultat d'extraction + métadonnées qualité (C0).

    Propagé jusqu'à `Article` : on sait DONC, par article, quelle stratégie a
    gagné, si le texte est intégral, s'il porte un marqueur de mur payant, et le
    score de confiance rendu par le scraper-service.
    """

    text: str | None = None
    method: str = "empty"           # curl_cffi | googlebot_referer | jina_ai | rss_full | cookies…
    is_full: bool | None = None     # texte intégral (vs chapô tronqué / page paywall)
    paywalled: bool | None = None   # marqueur de mur payant détecté
    confidence: float | None = None  # score de complétude (0..1), si fourni

    @property
    def ok(self) -> bool:
        return bool(self.text)


async def _via_service(url: str, base: str, timeout: int) -> Extraction | None:
    """Scraper-service v2 : on remonte le texte ET ses métadonnées qualité
    (`extraction_method`, `is_complete`, `confidence_score`) — pas seulement
    `content` — pour les écrire sur l'Article (C0)."""
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
    except Exception as exc:  # noqa: BLE001
        logger.debug("extractor.service_fail", url=url, error=str(exc)[:120])
        return None

    text = data.get("content") or data.get("text")
    if not text:
        return None
    return Extraction(
        text=text,
        method=data.get("extraction_method") or "service",
        is_full=data.get("is_complete"),
        paywalled=_is_paywalled(text),
        confidence=data.get("confidence_score"),
    )


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

# Marqueurs de mur payant / texte tronqué : un extrait qui les contient n'est PAS
# l'article complet, même s'il est long (page paywall = nav + chapô + teaser).
_PAYWALL_RE = re.compile(
    r"il vous reste\s+\d+|article réservé|réservé aux abonné|pour lire la suite|"
    r"abonnez-vous|déjà abonné|%\s+à lire|s['’]abonner pour lire|"
    r"soutenir.{0,30}journalisme|connectez-vous pour lire",
    re.IGNORECASE,
)


def _is_paywalled(text: str | None) -> bool:
    """Le texte porte-t-il un marqueur de mur payant (donc incomplet) ?"""
    return bool(text) and bool(_PAYWALL_RE.search(text[:4000]))


def build_extraction(
    text: str | None,
    method: str,
    *,
    is_full: bool | None = None,
    confidence: float | None = None,
) -> Extraction | None:
    """Emballe un texte brut en `Extraction` en calculant paywall/complétude.

    `is_full` non fourni ⇒ déduit : texte non-paywall et ≥ `_MIN_LEN`. Utilisé
    par les stratégies qui ne rendent qu'un `str` (trafilatura, jina, cookies…)
    et par `press_collector` pour les candidats RSS.
    """
    if not text:
        return None
    paywalled = _is_paywalled(text)
    if is_full is None:
        is_full = (not paywalled) and len(text) >= _MIN_LEN
    return Extraction(
        text=text, method=method, is_full=is_full,
        paywalled=paywalled, confidence=confidence,
    )


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


@lru_cache
def _site_cookies() -> dict[str, str]:
    """Mapping domaine → cookie d'abonné (depuis SITE_COOKIES, JSON). Vide si absent."""
    raw = get_settings().site_cookies.strip()
    if not raw:
        return {}
    try:
        return {k.lower(): v for k, v in json.loads(raw).items()}
    except Exception:  # noqa: BLE001
        logger.warning("extractor.site_cookies_invalid")
        return {}


def _cookie_for(url: str) -> str | None:
    host = urlparse(url).hostname or ""
    for domain, cookie in _site_cookies().items():
        if domain in host:
            return cookie
    return None


async def _via_cookies(url: str, timeout: int) -> str | None:
    """Récupère l'article en tant qu'ABONNÉ via les cookies de session fournis
    (SITE_COOKIES) — la façon la plus fiable de passer un paywall dur (Le Monde…)."""
    cookie = _cookie_for(url)
    if not cookie:
        return None
    headers = {**_browser_headers(), "Cookie": cookie}
    try:
        async with aiohttp.ClientSession(headers=headers) as http:
            async with http.get(
                url, timeout=aiohttp.ClientTimeout(total=timeout), allow_redirects=True
            ) as resp:
                if resp.status != 200:
                    return None
                html = await resp.text()
    except Exception as exc:  # noqa: BLE001
        logger.debug("extractor.cookies_fail", url=url, error=str(exc)[:120])
        return None
    return await asyncio.to_thread(_extract, html, recall=True)


async def _via_ladder(url: str, timeout: int) -> str | None:
    """ladder (everywall/ladder) auto-hébergé : proxy anti-paywall (GET {ladder}/{url})."""
    base = get_settings().ladder_url.strip().rstrip("/")
    if not base:
        return None
    try:
        async with aiohttp.ClientSession(headers=_browser_headers()) as http:
            async with http.get(
                f"{base}/{url}", timeout=aiohttp.ClientTimeout(total=timeout),
                allow_redirects=True,
            ) as resp:
                if resp.status != 200:
                    return None
                html = await resp.text()
    except Exception as exc:  # noqa: BLE001
        logger.debug("extractor.ladder_fail", url=url, error=str(exc)[:120])
        return None
    return await asyncio.to_thread(_extract, html, recall=True)


async def _via_removepaywall(url: str, timeout: int) -> str | None:
    """removepaywall.com : tente de servir l'article sans le mur. Best-effort
    (format variable → désactivé par défaut, mais filtré par le contrôle qualité)."""
    base = get_settings().removepaywall_url.rstrip("/")
    try:
        async with aiohttp.ClientSession(headers=_browser_headers()) as http:
            async with http.get(
                f"{base}/{url}", timeout=aiohttp.ClientTimeout(total=timeout),
                allow_redirects=True,
            ) as resp:
                if resp.status != 200:
                    return None
                html = await resp.text()
    except Exception as exc:  # noqa: BLE001
        logger.debug("extractor.removepaywall_fail", url=url, error=str(exc)[:120])
        return None
    return await asyncio.to_thread(_extract, html, recall=True)


async def _via_wayback(url: str, timeout: int) -> str | None:
    """Snapshot Wayback le plus proche, extrait : récupère souvent l'article
    complet d'une page aujourd'hui paywallée/403 (la capture date d'avant)."""
    from src.services.archive.wayback_availability import fetch_wayback_availability

    avail = await fetch_wayback_availability(url)
    snap = avail.get("closest_url")
    if not snap:
        return None
    try:
        async with aiohttp.ClientSession(headers=_browser_headers()) as http:
            async with http.get(
                snap, timeout=aiohttp.ClientTimeout(total=timeout), allow_redirects=True
            ) as resp:
                if resp.status != 200:
                    return None
                html = await resp.text()
    except Exception as exc:  # noqa: BLE001
        logger.debug("extractor.wayback_fail", url=url, error=str(exc)[:120])
        return None
    return await asyncio.to_thread(_extract, html, recall=True)


async def extract_fulltext(url: str) -> Extraction:
    """Texte d'article COMPLET via une cascade anti-blocage, précision d'abord.

    On préfère un extrait PROPRE (≥ _MIN_LEN et SANS marqueur de mur payant) à un
    extrait long mais tronqué (une page paywall est longue — nav + teaser — mais
    n'est pas l'article). Cascade :
      cookies → EXTRACTOR_URL (scraper-service v2) → ladder → trafilatura →
      Jina Reader → removepaywall → Wayback.
    On s'arrête dès qu'un extrait propre et complet est obtenu ; sinon on rend la
    meilleure `Extraction` propre, à défaut la plus longue. Le résultat porte la
    stratégie gagnante + les flags qualité (C0).
    """
    settings = get_settings()
    t = settings.request_timeout_seconds
    best_clean: Extraction | None = None  # le plus long SANS marqueur paywall
    best_any: Extraction | None = None    # le plus long tout court (dernier recours)

    def consider(ext: Extraction | None) -> bool:
        nonlocal best_clean, best_any
        if not ext or not ext.text:
            return False
        if best_any is None or len(ext.text) > len(best_any.text or ""):
            best_any = ext
        if not ext.paywalled and (
            best_clean is None or len(ext.text) > len(best_clean.text or "")
        ):
            best_clean = ext
        return bool(best_clean and len(best_clean.text or "") >= _MIN_LEN)

    # 0) cookies d'abonné (le plus fiable pour les paywalls durs souscrits)
    if consider(build_extraction(await _via_cookies(url, t * 2), "cookies")):
        return best_clean
    if settings.extractor_url.strip():
        if consider(await _via_service(url, settings.extractor_url, t * 4)):
            return best_clean
    if settings.ladder_url.strip() and consider(
        build_extraction(await _via_ladder(url, t * 2), "ladder")
    ):
        return best_clean
    if consider(build_extraction(await _via_trafilatura(url), "scraped")):
        return best_clean
    if settings.jina_reader_enabled and consider(
        build_extraction(await _via_jina(url, t * 2), "jina_ai")
    ):
        return best_clean
    if settings.removepaywall_enabled and consider(
        build_extraction(await _via_removepaywall(url, t * 2), "removepaywall")
    ):
        return best_clean
    if consider(build_extraction(await _via_wayback(url, t * 2), "wayback")):
        return best_clean
    return best_clean or best_any or Extraction()
