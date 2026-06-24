"""Helpers partagés (hash, nettoyage HTML, dates de flux, normalisation texte).

Factorise des fonctions auparavant dupliquées dans les collecteurs et
l'analyse : un seul endroit à tester et à faire évoluer.
"""

from __future__ import annotations

import hashlib
import html
import re
import unicodedata
from datetime import datetime, timezone
from time import mktime

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")
_STATUS_RE = re.compile(r"/status/(\d+)")


def sha256(text: str) -> str:
    """Hash hexadécimal stable d'une chaîne (clés de dédup)."""
    return hashlib.sha256(text.strip().encode()).hexdigest()


def clean_html(raw: str | None) -> str:
    """Retire les balises, décode TOUTES les entités (nommées + numériques),
    compacte les espaces."""
    text = _TAG_RE.sub(" ", raw or "")
    text = html.unescape(text)  # &#8217; → ’, &eacute; → é, etc.
    return _WS_RE.sub(" ", text).strip()


def feed_datetime(entry) -> datetime | None:
    """Datetime UTC d'une entrée feedparser (published puis updated)."""
    parsed = getattr(entry, "published_parsed", None) or getattr(
        entry, "updated_parsed", None
    )
    if not parsed:
        return None
    try:
        return datetime.fromtimestamp(mktime(parsed), tz=timezone.utc)
    except (ValueError, OverflowError):
        return None


def strip_accents(text: str) -> str:
    """Minuscule sans accents (matching lexical robuste)."""
    return "".join(
        c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c)
    ).lower()


def status_id(url: str) -> str | None:
    m = _STATUS_RE.search(url or "")
    return m.group(1) if m else None


def tweet_guid(handle: str, url: str) -> str:
    """Clé de dédup d'un tweet : hash de handle/status/<id> (ou de l'URL)."""
    sid = status_id(url)
    key = f"{handle.lower()}/status/{sid}" if sid else (url or "").strip()
    return sha256(key)
