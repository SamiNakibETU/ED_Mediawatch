"""Parser HTML des pages profil Nitter — engagement + date exacte + pagination.

Le RSS Nitter ne donne ni likes/RT/réponses/citations ni cursor de pagination.
On parse donc la page HTML (`.timeline-item`), avec les sélecteurs validés sur le
scraper du projet députés. Nécessite une source HTML accessible (Nitter
auto-hébergé en pratique ; le HTML public est challengé). Utilisé pour
l'enrichissement engagement ET le backfill (pagination par cursor).
"""

from __future__ import annotations

import re
from datetime import timezone

import structlog
from dateutil import parser as dateparser
from lxml import html as lxml_html

from src.utils import tweet_guid

logger = structlog.get_logger(__name__)

_NUM_RE = re.compile(r"([\d.,]+)\s*([KkMm])?")


def _parse_count(text: str) -> int | None:
    """Parse un compteur d'engagement Nitter en entier.

    Gère le plein (« 1 234 », « 1,234 », « 1.234 » → 1234) ET le compact
    (« 1.2K » → 1200, « 3M » → 3000000). Avant, « 1.2K » devenait 1 (le suffixe
    était ignoré et 1.2 tronqué) — or l'engagement est un critère §5.
    """
    text = (text or "").replace(" ", "").replace(" ", "")
    m = _NUM_RE.search(text)
    if not m:
        return 0
    raw, suffix = m.group(1), (m.group(2) or "").upper()
    try:
        if suffix:  # compact : le point/virgule est un séparateur décimal
            val = float(raw.replace(",", "."))
            return int(val * (1_000 if suffix == "K" else 1_000_000))
        # plein : ',' '.' ' ' sont des séparateurs de milliers → on les retire
        return int(raw.replace(",", "").replace(".", ""))
    except ValueError:
        return None


def _stat_value(item, icon_class: str) -> int | None:
    """Number in the .tweet-stat that contains the given icon (e.g. icon-heart)."""
    icons = item.cssselect(f".tweet-stats .{icon_class}")
    if not icons:
        return None
    # climb to the enclosing .tweet-stat and read its text number
    node = icons[0]
    for _ in range(4):
        node = node.getparent()
        if node is None:
            return None
        cls = node.get("class") or ""
        if "tweet-stat" in cls:
            break
    return _parse_count(node.text_content())


def _parse_date(item, handle: str) -> datetime | None:
    links = item.cssselect(".tweet-date a")
    if not links:
        return None
    title = links[0].get("title")  # e.g. "Jun 20, 2026 · 1:56 PM UTC"
    if not title:
        return None
    try:
        dt = dateparser.parse(title.replace("·", "").replace(" UTC", ""))
        if dt and dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, OverflowError):
        return None


def _tweet_link(item) -> str:
    for sel in (".tweet-date a", "a.tweet-link"):
        els = item.cssselect(sel)
        if els and els[0].get("href"):
            return els[0].get("href")
    return ""


def parse_profile_html(
    html_text: str, handle: str, base_url: str = ""
) -> tuple[list[dict], str | None]:
    """Return (posts, next_cursor). posts carry engagement + exact date."""
    doc = lxml_html.fromstring(html_text)
    posts: list[dict] = []

    for item in doc.cssselect(".timeline-item"):
        cls = item.get("class") or ""
        if "show-more" in cls or "unavailable" in cls:
            continue
        content_els = item.cssselect(".tweet-content")
        if not content_els:
            continue
        content = content_els[0].text_content().strip()
        if not content:
            continue

        link = _tweet_link(item)
        if base_url and link.startswith("/"):
            full_link = base_url.rstrip("/") + link
        else:
            full_link = link

        is_retweet = bool(item.cssselect(".retweet-header"))
        is_reply = bool(item.cssselect(".replying-to"))
        media = item.cssselect(".attachment.image img, .still-image img, video")
        media_url = (media[0].get("src") or media[0].get("data-url")) if media else None
        if media_url and base_url and media_url.startswith("/"):
            media_url = base_url.rstrip("/") + media_url

        posts.append(
            {
                "guid": tweet_guid(handle, link),
                "url": full_link,
                "content": content,
                "published_at": _parse_date(item, handle),
                "is_retweet": is_retweet,
                "is_reply": is_reply,
                "media_url": media_url,
                "collected_via": "html",
                "replies": _stat_value(item, "icon-comment"),
                "retweets": _stat_value(item, "icon-retweet"),
                "quotes": _stat_value(item, "icon-quote"),
                "likes": _stat_value(item, "icon-heart"),
                "word_count": len(content.split()),
            }
        )

    # next page cursor
    next_cursor: str | None = None
    for a in doc.cssselect(".show-more a"):
        href = a.get("href") or ""
        if "cursor=" in href:
            next_cursor = href
            break

    return posts, next_cursor
