"""Stratégies de contournement de paywall additionnelles (SPEC §3.1 T3-T6).

Trois nouvelles stratégies plug-and-play dans `UltimateExtractor` :

  - googlebot_referer : User-Agent Googlebot + Referer https://www.google.com/
    → encore efficace mi-2026 sur Le Monde, Le Figaro, Haaretz partial,
    NYT first-click-free et plusieurs sites premium qui servent un contenu
    différent au crawler de Google. Aucun coût.

  - archive_ph : soumet l'URL à archive.ph via /submit/?url=... puis lit
    la page archivée. Backup gratuit pour les sites où Googlebot échoue.

  - llm_cleanup : envoie le markdown / le texte le plus long obtenu par les
    autres stratégies à un LLM cheap (Groq Llama 4 Scout par défaut) pour
    extraire le corps de l'article propre. Tier final, ~$0.0003/article.

Les fonctions retournent le même contrat que les stratégies existantes :
    Optional[Dict[str, Any]] avec au moins title/content/word_count/method.

Les imports lourds (httpx, structlog) sont locaux pour ne pas péter le
chargement si on désactive le module.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
from typing import Any, Optional
from urllib.parse import quote_plus, urlparse

import structlog

logger = structlog.get_logger(__name__)


GOOGLEBOT_UA = "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)"
GOOGLEBOT_REFERER = "https://www.google.com/"


_PAYWALL_RESIDUE_RX = re.compile(
    r"(abonnez[\-\s]?vous|s'abonner|subscribe (now|to read)|continue reading|"
    r"להמשך\s+קריאה|اشترك\s+(الآن|للقراءة)|"
    r"sign\s+(up|in)\s+to\s+(read|continue))",
    re.IGNORECASE,
)


def looks_paywalled(text: str | None) -> bool:
    if not text:
        return True
    if len(text.split()) < 200:
        return True
    hits = len(_PAYWALL_RESIDUE_RX.findall(text))
    # Plus de 2 hits dans le texte = boilerplate paywall
    return hits >= 2


# ---------------------------- GOOGLEBOT --------------------------------------

async def extract_googlebot_referer(url: str, timeout_s: float = 25.0) -> Optional[dict]:
    """T3 — User-Agent Googlebot + Referer Google.

    Beaucoup de sites premium servent le full-text à Googlebot (pour le
    référencement) ou à un trafic provenant de Google (first-click-free).
    Combiner les deux maximise les chances.
    """
    try:
        import httpx
    except ImportError:
        return None

    headers = {
        "User-Agent": GOOGLEBOT_UA,
        "Referer": GOOGLEBOT_REFERER,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8,he;q=0.6,ar;q=0.5",
        "Accept-Encoding": "gzip, deflate, br",
        "DNT": "1",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Cache-Control": "no-cache",
    }
    try:
        async with httpx.AsyncClient(timeout=timeout_s, follow_redirects=True) as client:
            r = await client.get(url, headers=headers)
            if r.status_code != 200:
                logger.debug(
                    "extract.googlebot.bad_status",
                    url=url[:120],
                    status=r.status_code,
                )
                return None
            html = r.text
    except Exception as exc:
        logger.debug("extract.googlebot.error", url=url[:120], error=str(exc)[:120])
        return None

    return _parse_html_minimal(html, url, method="googlebot_referer")


# ---------------------------- ARCHIVE.PH -------------------------------------

ARCHIVE_PH_HOSTS = ("https://archive.ph", "https://archive.today", "https://archive.is")


async def extract_archive_ph(url: str, timeout_s: float = 30.0) -> Optional[dict]:
    """T4 — archive.ph submit-and-fetch.

    On essaie d'abord `archive.ph/newest/<url>` (le plus rapide si déjà
    indexé). Si 404/500, on tente `submit/?url=` puis on suit la redirection.
    Cloudflare-protégé donc on utilise de simples requêtes GET avec UA
    navigateur.
    """
    try:
        import httpx
    except ImportError:
        return None

    ua = (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    )
    headers = {"User-Agent": ua, "Accept": "text/html,*/*;q=0.8"}

    for base in ARCHIVE_PH_HOSTS:
        # 1) version indexée la plus récente
        newest = f"{base}/newest/{url}"
        try:
            async with httpx.AsyncClient(
                timeout=timeout_s, follow_redirects=True, headers=headers
            ) as client:
                r = await client.get(newest)
                if r.status_code == 200 and len(r.text or "") > 5000:
                    parsed = _parse_html_minimal(r.text, url, method="archive_ph_newest")
                    if parsed and parsed.get("word_count", 0) >= 200:
                        return parsed
        except Exception as exc:
            logger.debug(
                "extract.archive_ph.newest_fail",
                base=base,
                error=str(exc)[:120],
            )
            continue

    # 2) submit (best effort, peut prendre 10-30s côté archive.ph)
    base = ARCHIVE_PH_HOSTS[0]
    submit_url = f"{base}/submit/?url={quote_plus(url)}"
    try:
        async with httpx.AsyncClient(
            timeout=timeout_s, follow_redirects=True, headers=headers
        ) as client:
            r = await client.get(submit_url)
            if r.status_code == 200 and len(r.text or "") > 5000:
                return _parse_html_minimal(r.text, url, method="archive_ph_submit")
    except Exception as exc:
        logger.debug("extract.archive_ph.submit_fail", error=str(exc)[:120])

    return None


# ---------------------------- LLM CLEANUP ------------------------------------

# ED_Mediawatch : le compte Groq est bloqué (impayé) → on défaut sur **Cerebras**
# (OpenAI-compatible, `gpt-oss-120b`). Surchargeable via env. On accepte encore
# GROQ_API_KEY en dernier repli si le compte est un jour réactivé.
DEFAULT_LLM_CLEANUP_MODEL = os.getenv(
    "SCRAPER_LLM_CLEANUP_MODEL", "gpt-oss-120b"
)
DEFAULT_LLM_CLEANUP_BASE_URL = os.getenv(
    "SCRAPER_LLM_CLEANUP_BASE_URL", "https://api.cerebras.ai/v1"
)
LLM_CLEANUP_API_KEY = (
    os.getenv("CEREBRAS_API_KEY", "")
    or os.getenv("SCRAPER_LLM_CLEANUP_API_KEY", "")
    or os.getenv("GROQ_API_KEY", "")
)

CLEANUP_SYSTEM_PROMPT = (
    "You are a news article extractor. Given messy markdown of a news page, "
    "return ONLY the article body in its original language. Strip: ads, "
    "social share buttons, 'you may also like', comments, subscription CTAs "
    "('Subscribe', 'Abonnez-vous', 'להמשך קריאה', 'اشترك'), sponsored content, "
    "breadcrumbs, related-article lists, navigation. Reply ONLY with a strict "
    "JSON object: {\"title\": str|null, \"author\": str|null, \"published_at\": "
    "str|null, \"language\": str|null, \"body\": str, \"is_paywalled_truncated\""
    ": bool}. The 'body' is the article only; do not summarize, do not "
    "translate. If you cannot extract a body, return body as empty string."
)


async def extract_llm_cleanup(
    url: str,
    raw_text: str,
    *,
    timeout_s: float = 30.0,
    max_input_chars: int = 60_000,
) -> Optional[dict]:
    """T6 — LLM cleanup sur le texte le plus long déjà obtenu.

    Tier final : on n'appelle ce LLM que si toutes les autres stratégies ont
    livré un texte ≥200 mots mais avec marqueurs paywall. Le LLM débroussaille
    et renvoie un JSON strict.

    Coût ~$0.0002-0.0005 / article avec Llama 4 Scout sur Groq.
    """
    if not LLM_CLEANUP_API_KEY:
        logger.debug("extract.llm_cleanup.no_api_key")
        return None
    if not raw_text or len(raw_text) < 400:
        return None
    try:
        import httpx
    except ImportError:
        return None

    truncated = raw_text[:max_input_chars]
    body = {
        "model": DEFAULT_LLM_CLEANUP_MODEL,
        "messages": [
            {"role": "system", "content": CLEANUP_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": f"<url>{url}</url>\n<page_markdown>\n{truncated}\n</page_markdown>",
            },
        ],
        "temperature": 0.0,
        "response_format": {"type": "json_object"},
        "max_tokens": 4096,
    }
    headers = {
        "Authorization": f"Bearer {LLM_CLEANUP_API_KEY}",
        "Content-Type": "application/json",
    }
    endpoint = f"{DEFAULT_LLM_CLEANUP_BASE_URL.rstrip('/')}/chat/completions"

    try:
        async with httpx.AsyncClient(timeout=timeout_s) as client:
            r = await client.post(endpoint, json=body, headers=headers)
            r.raise_for_status()
            payload = r.json()
    except Exception as exc:
        logger.warning("extract.llm_cleanup.request_failed", error=str(exc)[:200])
        return None

    try:
        content = payload["choices"][0]["message"]["content"]
        parsed = json.loads(content) if isinstance(content, str) else content
    except (KeyError, IndexError, json.JSONDecodeError, TypeError) as exc:
        logger.warning("extract.llm_cleanup.parse_failed", error=str(exc)[:200])
        return None

    cleaned_body = (parsed.get("body") or "").strip()
    if not cleaned_body or len(cleaned_body.split()) < 80:
        return None

    return {
        "url": url,
        "title": parsed.get("title") or None,
        "author": parsed.get("author") or None,
        "date": parsed.get("published_at") or None,
        "language": parsed.get("language") or None,
        "content": cleaned_body,
        "word_count": len(cleaned_body.split()),
        "extraction_method": "llm_cleanup",
        "is_paywalled_truncated": bool(parsed.get("is_paywalled_truncated")),
    }


# ---------------------------- PARSER MINIMAL ---------------------------------

def _parse_html_minimal(html: str, url: str, method: str) -> Optional[dict]:
    """Extraction minimale via trafilatura ; renvoie le contrat standard.

    On délègue à trafilatura pour rester cohérent avec le reste du service.
    Si trafilatura indisponible (rare), fallback regex.
    """
    text = ""
    title = None
    author = None
    pub_date = None
    try:
        import trafilatura

        text = (
            trafilatura.extract(
                html,
                favor_precision=True,
                include_comments=False,
                include_tables=False,
                output_format="txt",
            )
            or ""
        )
        meta = trafilatura.extract_metadata(html)
        if meta:
            title = (meta.title or None)
            author = (meta.author or None)
            pub_date = (meta.date or None)
    except Exception:
        # Fallback : strip basique des balises
        text = re.sub(r"<script[\s\S]*?</script>", " ", html or "")
        text = re.sub(r"<style[\s\S]*?</style>", " ", text)
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"\s+", " ", text).strip()

    if not text or len(text.split()) < 80:
        return None

    return {
        "url": url,
        "title": title,
        "author": author,
        "date": pub_date,
        "content": text,
        "word_count": len(text.split()),
        "extraction_method": method,
    }


# ---------------------------- ORCHESTRATOR -----------------------------------

async def try_paywall_bypass_chain(url: str) -> list[dict]:
    """Lance googlebot puis archive.ph en parallèle ; retourne les succès."""
    results = await asyncio.gather(
        extract_googlebot_referer(url),
        extract_archive_ph(url),
        return_exceptions=True,
    )
    out: list[dict] = []
    for r in results:
        if isinstance(r, dict):
            out.append(r)
    return out


def is_premium_domain(url: str) -> bool:
    """Domaines connus pour avoir un paywall actif → vaut le coup d'essayer T3-T6."""
    host = (urlparse(url).netloc or "").lower()
    premium = (
        "haaretz.com",
        "lemonde.fr",
        "lefigaro.fr",
        "nytimes.com",
        "wsj.com",
        "ft.com",
        "thetimes.co.uk",
        "telegraph.co.uk",
        "washingtonpost.com",
        "bloomberg.com",
        "economist.com",
    )
    return any(host.endswith(d) or d in host for d in premium)
