"""Collecte X via l'endpoint de syndication OFFICIEL (widgets embarqués).

Après la mise en demeure de X Corp contre Nitter (24 août 2026), imiter le site
n'est plus une option. Mais X laisse une porte ouverte par construction : le
service qui alimente les timelines EMBARQUÉES sur les sites tiers —
`syndication.twitter.com/srv/timeline-profile/screen-name/<handle>` — sert la
page rendue par Next.js avec, dans `__NEXT_DATA__`, ~20 tweets récents complets :
texte intégral, date exacte, compteurs (likes/RT/réponses/citations), langue,
`retweeted_status`, `quoted_status`, réponse-à. Sans compte, sans cookie, sans
proxy. C'est l'endpoint que `publish.twitter.com/oembed` référence lui-même.

Vérifié le 26/08/2026 : HTTP 200, 39 identifiants pour @J_Bardella, plus riche
que le RSS Nitter (qui n'avait ni engagement ni distinction quote/RT).

Limites assumées : ~20 tweets par appel (pas de pagination) — suffisant pour
une collecte toutes les 4 h, insuffisant pour un backfill (→ Wayback CDX +
fxtwitter, cf. `x_backfill`). Rate-limit ponctuel (429) : on retente une fois
après pause, puis on laisse la main au repli Nitter s'il existe encore.
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from datetime import datetime, timezone

import httpx
import structlog

from src.config import get_settings
from src.utils import tweet_guid

logger = structlog.get_logger(__name__)

SYNDICATION_URL = "https://syndication.twitter.com/srv/timeline-profile/screen-name/{handle}"
_NEXT_DATA_RE = re.compile(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S)
# Format de date de l'API X : « Mon Aug 24 08:11:35 +0000 2026 »
_DATE_FMT = "%a %b %d %H:%M:%S %z %Y"
COLLECTED_VIA = "synd"  # ≤ 8 car. (Post.collected_via)
# Seuil de soupçon de troncature (limite classique 280 ; vérifié : un
# note tweet de 501 caractères arrive coupé à 280 en syndication).
TRUNCATION_HINT = 270


def _parse_date(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        return datetime.strptime(raw, _DATE_FMT).astimezone(timezone.utc)
    except ValueError:
        return None


def _expand_urls(text: str, entities: dict | None) -> str:
    """Remplace les t.co par l'URL réelle (lisibilité + verbatim honnête)."""
    for u in (entities or {}).get("urls", []) or []:
        short, full = u.get("url"), u.get("expanded_url")
        if short and full:
            text = text.replace(short, full)
    return text


def _media_url(tweet: dict) -> str | None:
    """Premier média. Pour une vidéo, la variante mp4 au meilleur débit (leçon du
    parseur Nitter, `parseVideoVariants`) plutôt que la vignette : c'est la piste
    audio dont la phase TV/ASR aura besoin."""
    ext = tweet.get("extended_entities") or tweet.get("entities") or {}
    for m in ext.get("media", []) or []:
        if m.get("type") in ("video", "animated_gif"):
            mp4s = [
                v for v in (m.get("video_info") or {}).get("variants", []) or []
                if v.get("content_type") == "video/mp4" and v.get("url")
            ]
            if mp4s:
                best = max(mp4s, key=lambda v: v.get("bitrate") or v.get("bit_rate") or 0)
                return best["url"]
        return m.get("media_url_https") or m.get("media_url")
    return None


def _tweet_dict(tweet: dict, handle: str) -> dict | None:
    """Normalise un tweet syndication vers le dict attendu par `_insert_new`."""
    tid = tweet.get("id_str")
    author = (tweet.get("user") or {}).get("screen_name") or handle
    if not tid:
        return None

    rt = tweet.get("retweeted_status")
    quoted = tweet.get("quoted_status")
    reply_to = tweet.get("in_reply_to_screen_name")

    # Pour un RT, le texte utile est celui du tweet d'origine (pas « RT @x: … »).
    body = rt or tweet
    raw = body.get("full_text") or body.get("text") or ""
    # display_text_range (leçon du parseur Nitter) : borne le texte AFFICHÉ —
    # exclut les @mentions de tête d'une réponse et le lien média de queue.
    # Indices en points de code, pas en octets.
    rng = body.get("display_text_range") or [0, len(raw)]
    try:
        start, end = int(rng[0]), int(rng[1])
        runes = list(raw)
        shown = "".join(runes[start:end]) if 0 <= start <= end <= len(runes) else raw
    except (TypeError, ValueError):
        shown, end = raw, len(raw)
    text = _expand_urls(shown, body.get("entities")).strip()
    if not text:
        return None
    # La syndication coupe à 280 : un texte affiché qui touche la limite est
    # probablement un « note tweet » tronqué → texte intégral à récupérer par ID.
    truncated = (end - start) >= TRUNCATION_HINT

    is_retweet = rt is not None
    is_reply = bool(reply_to)
    post_type = (
        "retweet" if is_retweet
        else "quote" if quoted is not None
        else "reply" if is_reply
        else "original"
    )
    url = f"https://x.com/{author}/status/{tid}"

    out = {
        "guid": tweet_guid(handle, url),
        "url": url,
        "content": text,
        "published_at": _parse_date(tweet.get("created_at")),
        "is_retweet": is_retweet,
        "is_reply": is_reply,
        "post_type": post_type,
        "reply_to_handle": reply_to,
        "reply_to_url": (
            f"https://x.com/{reply_to}/status/{tweet['in_reply_to_status_id_str']}"
            if reply_to and tweet.get("in_reply_to_status_id_str") else None
        ),
        "media_url": _media_url(body),
        "likes": tweet.get("favorite_count"),
        "retweets": tweet.get("retweet_count"),
        "replies": tweet.get("reply_count"),
        "quotes": tweet.get("quote_count"),
        "collected_via": COLLECTED_VIA,
        "lang": (tweet.get("lang") or "fr")[:8],
        "word_count": len(text.split()),
        "text_truncated": truncated,
        # Toujours présentes (None si pas de citation) : l'INSERT multi-lignes
        # exige le MÊME jeu de clés sur toutes les lignes d'un lot — sinon tout
        # le lot du handle échoue (« explicitly rendered as… »), vu en prod.
        "quoted_handle": None,
        "quoted_url": None,
        "quoted_content": None,
    }
    # Le post PORTÉ, citation comme retweet. `retweeted_status` était déjà lu
    # pour en prendre le texte, mais son auteur était jeté : 1 438 retweets sur
    # 1 455 n'avaient aucune cible en base, et un retweet sans cible n'est pas un
    # signal d'amplification — c'est une ligne morte.
    #
    # Même paire de champs pour les deux : `post_type` dit déjà lequel c'est, et
    # deux paires de colonnes quasi identiques se désynchronisent toujours.
    carried = quoted if quoted is not None else rt
    if carried is not None:
        c_user = (carried.get("user") or {}).get("screen_name")
        c_id = carried.get("id_str")
        out["quoted_handle"] = c_user
        out["quoted_url"] = f"https://x.com/{c_user}/status/{c_id}" if c_user and c_id else None
        # Pour un retweet, `content` porte déjà ce texte : ne pas le dupliquer.
        # ATTENTION : ce sont alors les mots de QUELQU'UN D'AUTRE. C'est pour ça
        # que l'extraction L0 exclut `is_retweet` — ne jamais relâcher ce filtre
        # sans traiter le cas, sous peine de prêter à une figure les propos
        # qu'elle relaie.
        if quoted is not None:
            out["quoted_content"] = _expand_urls(
                quoted.get("full_text") or quoted.get("text") or "", quoted.get("entities")
            )[:2000] or None
    return out


def parse_profile(html: str, handle: str) -> dict | None:
    """Métadonnées de compte tirées du bloc `user` des tweets (id stable, audience)."""
    m = _NEXT_DATA_RE.search(html or "")
    if not m:
        return None
    try:
        entries = json.loads(m.group(1))["props"]["pageProps"]["timeline"]["entries"]
    except (json.JSONDecodeError, KeyError, TypeError):
        return None
    for e in entries:
        u = ((e.get("content") or {}).get("tweet") or {}).get("user") or {}
        if (u.get("screen_name") or "").lower() == handle.lower():
            return {
                "x_user_id": u.get("id_str"),
                "followers_count": u.get("followers_count"),
                "statuses_count": u.get("statuses_count"),
                "x_protected": bool(u.get("protected", False)),
            }
    return None


def parse_syndication(html: str, handle: str) -> list[dict]:
    """Extrait les tweets de la page syndication (JSON `__NEXT_DATA__`)."""
    m = _NEXT_DATA_RE.search(html or "")
    if not m:
        return []
    try:
        data = json.loads(m.group(1))
        entries = data["props"]["pageProps"]["timeline"]["entries"]
    except (json.JSONDecodeError, KeyError, TypeError):
        return []
    out: list[dict] = []
    for e in entries:
        tweet = (e.get("content") or {}).get("tweet")
        if not tweet:
            continue
        d = _tweet_dict(tweet, handle)
        if d:
            out.append(d)
    return out


def _is_cloudflare_html(body: str) -> bool:
    """Page d'erreur Cloudflare rendue à la place du contenu (cf. Nitter)."""
    head = (body or "")[:14].lower()
    return head.startswith("<!doctype html") and "cloudflare" in (body or "").lower()


def timeline_state(html: str) -> str:
    """État d'un compte d'après la page syndication, pour la santé par handle :
    « ok » (tweets), « empty » (compte protégé, suspendu, inexistant ou muet)."""
    m = _NEXT_DATA_RE.search(html or "")
    if not m:
        return "empty"
    try:
        entries = json.loads(m.group(1))["props"]["pageProps"]["timeline"]["entries"]
    except (json.JSONDecodeError, KeyError, TypeError):
        return "empty"
    return "ok" if any((e.get("content") or {}).get("tweet") for e in entries) else "empty"


class SyndicationClient:
    """Client poli : concurrence bornée, délai entre requêtes, un retry sur 429."""

    def __init__(self) -> None:
        s = get_settings()
        # En série : l'endpoint tolère mal les rafales (429 sur les derniers
        # handles d'une passe à 3 en parallèle). 113 handles × ~3 s ≈ 6 min,
        # largement dans le pas de 4 h du scheduler.
        self._sem = asyncio.Semaphore(1)
        # Quota annoncé par le serveur (x-rate-limit-*) : on le respecte plutôt
        # que de le deviner. remaining=0 → on dort jusqu'au reset (epoch).
        self.last_profile: dict | None = None
        self._remaining: int | None = None
        self._reset_at: float | None = None
        self._delay = s.request_delay_seconds
        self._timeout = s.request_timeout_seconds
        self._headers = {
            "User-Agent": s.user_agent,
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
        }

    async def fetch_timeline(self, handle: str) -> str | None:
        url = SYNDICATION_URL.format(handle=handle)
        async with self._sem:
            async with httpx.AsyncClient(timeout=self._timeout, headers=self._headers,
                                         follow_redirects=True) as client:
                # Rate-limit IP observé en passe complète (429 puis connexions
                # refusées après ~30 handles en rafale). Backoff exponentiel :
                # 10 s, 30 s, 90 s — puis on rend la main ; la santé par handle
                # (C4) fera reprendre les manquants à la passe suivante.
                for attempt, pause in enumerate((10, 30, 90), start=1):
                    await self._wait_for_quota()
                    try:
                        r = await client.get(url)
                    except httpx.HTTPError as exc:
                        logger.warning("synd.http_error", handle=handle,
                                       attempt=attempt, error=str(exc)[:120])
                        await asyncio.sleep(pause)
                        continue
                    self._read_quota(r.headers)
                    if r.status_code == 200 and "__NEXT_DATA__" in r.text:
                        await asyncio.sleep(self._delay)
                        return r.text
                    # Leçons Nitter (apiutils.nim) : un 404 à corps vide est
                    # transitoire (on retente), et une page HTML Cloudflare
                    # servie à la place du contenu est un blocage, pas une
                    # absence de compte.
                    if r.status_code == 404 and not r.text.strip():
                        logger.info("synd.transient_404", handle=handle, attempt=attempt)
                        await asyncio.sleep(pause)
                        continue
                    if _is_cloudflare_html(r.text):
                        logger.warning("synd.cloudflare_block", handle=handle, status=r.status_code)
                        await asyncio.sleep(pause)
                        continue
                    if r.status_code == 429:
                        # Sans en-tête reset, backoff classique ; avec, on
                        # dort exactement jusqu'à la fenêtre suivante.
                        wait = self._seconds_to_reset() or pause
                        logger.info("synd.rate_limited", handle=handle, attempt=attempt, wait=round(wait))
                        await asyncio.sleep(wait)
                        continue
                    logger.info("synd.unavailable", handle=handle, status=r.status_code)
                    return None
        return None

    def _read_quota(self, headers) -> None:
        try:
            rem = headers.get("x-rate-limit-remaining")
            rst = headers.get("x-rate-limit-reset")
            if rem is not None:
                self._remaining = int(rem)
            if rst is not None:
                self._reset_at = float(rst)
        except (TypeError, ValueError):
            pass

    def _seconds_to_reset(self) -> float:
        if not self._reset_at:
            return 0.0
        return max(0.0, self._reset_at - time.time() + 1.0)

    async def _wait_for_quota(self) -> None:
        """Quota épuisé (annoncé par le serveur) → attendre le reset, pas un 429."""
        if self._remaining is not None and self._remaining <= 0:
            wait = self._seconds_to_reset()
            if wait > 0:
                logger.info("synd.quota_wait", seconds=round(wait))
                await asyncio.sleep(wait)
            self._remaining = None

    async def collect(self, handle: str) -> list[dict] | None:
        """Tweets normalisés, ou None si l'endpoint n'a pas répondu (→ repli).
        Le profil du dernier appel est disponible dans `last_profile`."""
        html = await self.fetch_timeline(handle)
        if html is None:
            self.last_profile = None
            return None
        posts = parse_syndication(html, handle)
        self.last_profile = parse_profile(html, handle)
        logger.info("synd.collected", handle=handle, tweets=len(posts))
        return posts

