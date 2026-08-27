"""Backfill historique X sans compte : Wayback CDX (identifiants) + fxtwitter (contenu).

La syndication (`x_syndication`) ne rend que les ~20-100 derniers tweets d'un
handle : parfait pour le flux, inutile pour le *position drift* qui exige des
années. Deux sources gratuites se complètent :

  * **Wayback CDX** (`web.archive.org/cdx/search/cdx?url=x.com/<handle>/status/*`)
    liste tous les statuts qu'Internet Archive a capturés — pour une personnalité
    politique, des milliers, capturés au fil de l'eau par des tiers (presse,
    veilles, bots). On n'y lit pas le contenu (pages X rendues en JS, capture
    vide) : on y lit les IDENTIFIANTS.
  * **fxtwitter** (`api.fxtwitter.com/<handle>/status/<id>`) rend, pour un
    identifiant, le tweet complet : texte, date, likes/RT/réponses/vues, citation,
    réponse-à, langue. Service tiers gratuit très diffusé (embeds Discord/Telegram).

Vérifié le 26/08/2026 : CDX liste des statuts @J_Bardella capturés en août 2026 ;
fxtwitter rend un tweet de juillet 2026 avec 931 538 vues.

Coût zéro. Rythme poli (série, délai) : fxtwitter n'est pas à nous, on ne le
sature pas. Idempotent : un identifiant déjà en base n'est jamais re-demandé.
Dépendance tierce assumée : si fxtwitter disparaît, le backfill s'arrête — le
flux courant (syndication, endpoint X officiel) n'en dépend pas.
"""

from __future__ import annotations

import asyncio
import re
from datetime import datetime, timezone

import httpx
import structlog
from sqlalchemy import func, select

from src.config import get_settings
from src.database import get_session_factory
from src.models.personality import Personality
from src.models.post import Post
from src.utils import tweet_guid

logger = structlog.get_logger(__name__)

CDX_URL = "https://web.archive.org/cdx/search/cdx"
FX_URL = "https://api.fxtwitter.com/{handle}/status/{tid}"
_STATUS_RE = re.compile(r"/status/(\d{15,20})")
COLLECTED_VIA = "fxtw"  # ≤ 8 car.
CDX_PAUSE_SECONDS = 1.0  # politesse entre requêtes CDX (0 dans les tests)
_FX_DATE_FMT = "%a %b %d %H:%M:%S %z %Y"


# Snowflake X : id >> 22 = millisecondes depuis l'epoch Twitter (2010-11-04
# 01:42:54.657 UTC). L'identifiant PORTE la date du tweet — on filtre dessus,
# car `from=` côté CDX filtre la date de CAPTURE (un tweet de 2019 capturé en
# 2026 passe), ce qui ramenait l'historique le plus ancien au lieu du récent.
_TWITTER_EPOCH_MS = 1288834974657


def snowflake_floor(year: int) -> int:
    """Plus petit identifiant possible pour un tweet publié à partir du 1er janvier `year`."""
    ms = int(datetime(year, 1, 1, tzinfo=timezone.utc).timestamp() * 1000) - _TWITTER_EPOCH_MS
    return max(0, ms) << 22


def _id_prefixes(since_year: int) -> list[str]:
    """Préfixes d'identifiants couvrant [1er janvier `since_year`, maintenant].

    Les snowflakes croissent avec le temps : leurs premiers chiffres découpent
    donc l'axe temporel. Interroger CDX par préfixe (`status/19*`) divise une
    requête qui tombe en 504 sur un gros compte en quelques requêtes de 2-20 s.
    """
    lo = str(snowflake_floor(since_year))
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000) - _TWITTER_EPOCH_MS
    hi = str(now_ms << 22)
    if len(lo) != len(hi):
        # Changement de nombre de chiffres (rare) : on couvre large.
        return [str(d) for d in range(int(lo[:1]), 10)] + [str(d) for d in range(1, int(hi[:1]) + 1)]
    return [str(v) for v in range(int(lo[:2]), int(hi[:2]) + 1)]


async def _cdx_ids(client: httpx.AsyncClient, url_pattern: str, floor: int) -> set[int]:
    params = {"url": url_pattern, "fl": "original", "limit": "3000"}
    try:
        r = await client.get(CDX_URL, params=params, timeout=90)
    except httpx.HTTPError as exc:
        logger.warning("backfill.cdx_error", url=url_pattern, error=str(exc)[:100])
        return set()
    if r.status_code != 200:
        logger.info("backfill.cdx_unavailable", url=url_pattern, status=r.status_code)
        return set()
    out: set[int] = set()
    for m in _STATUS_RE.finditer(r.text):
        tid = int(m.group(1))
        if tid >= floor:
            out.add(tid)
    return out


async def list_archived_ids(
    client: httpx.AsyncClient, handle: str, *, since_year: int, limit: int
) -> list[str]:
    """Identifiants de statuts capturés par Wayback, publiés depuis `since_year`,
    du plus récent au plus ancien (le drift se lit d'abord sur les années proches).

    Découpage par préfixe d'identifiant (tranches temporelles) et par domaine :
    les captures antérieures au rebranding vivent sous `twitter.com`, les
    récentes sous `x.com` — les deux comptent. Dédup côté client (pas de
    `collapse` côté serveur : c'est lui qui fait tomber les gros comptes).
    """
    floor = snowflake_floor(since_year)
    prefixes = _id_prefixes(since_year)
    by_slice: list[set[int]] = []
    for pfx in prefixes:
        found: set[int] = set()
        for domain in ("x.com", "twitter.com"):
            found |= await _cdx_ids(client, f"{domain}/{handle}/status/{pfx}*", floor)
            if CDX_PAUSE_SECONDS:
                await asyncio.sleep(CDX_PAUSE_SECONDS)
        by_slice.append(found)
    # Quota RÉPARTI entre tranches temporelles (plus récent d'abord dans chaque
    # tranche) : garder simplement les 300 plus récents donnait 267 tweets de
    # 2026 et rien avant — inutilisable pour lire une évolution de position.
    # Le reliquat des tranches pauvres est redistribué aux tranches riches.
    ids: list[int] = []
    remaining = limit
    slices = [sorted(sl, reverse=True) for sl in by_slice if sl]
    while remaining > 0 and slices:
        share = max(1, remaining // len(slices))
        taken = []
        for sl in slices:
            chunk = sl[:share]
            taken.extend(chunk)
            del sl[:share]
        if not taken:
            break
        ids.extend(taken)
        remaining -= len(taken)
        slices = [sl for sl in slices if sl]
    ids_out = [str(t) for t in sorted(set(ids), reverse=True)[:limit]]
    logger.info("backfill.cdx_ids", handle=handle, ids=len(ids_out),
                total_found=sum(len(sl) for sl in by_slice), slices=len(prefixes),
                since_year=since_year)
    return ids_out


def _fx_to_post(data: dict, handle: str) -> dict | None:
    """Normalise une réponse fxtwitter vers le dict attendu par `_insert_new`."""
    t = data.get("tweet") or {}
    tid, text = t.get("id"), (t.get("text") or "").strip()
    if not tid or not text:
        return None
    author = (t.get("author") or {}).get("screen_name") or handle
    # Un tweet rendu sous un autre auteur que le handle demandé = RT/repost.
    is_retweet = author.lower() != handle.lower()
    quote = t.get("quote")
    reply_to = t.get("replying_to")
    try:
        published = datetime.strptime(t["created_at"], _FX_DATE_FMT).astimezone(timezone.utc)
    except (KeyError, ValueError):
        ts = t.get("created_timestamp")
        published = datetime.fromtimestamp(ts, tz=timezone.utc) if ts else None
    url = t.get("url") or f"https://x.com/{author}/status/{tid}"
    media = ((t.get("media") or {}).get("all") or [{}])[0].get("url")
    out = {
        "guid": tweet_guid(handle, url),
        "url": url,
        "content": text,
        "published_at": published,
        "is_retweet": is_retweet,
        "is_reply": bool(reply_to),
        "post_type": (
            "retweet" if is_retweet else "quote" if quote else "reply" if reply_to else "original"
        ),
        "reply_to_handle": reply_to,
        "media_url": media,
        "likes": t.get("likes"),
        "retweets": t.get("retweets"),
        "replies": t.get("replies"),
        "views": t.get("views"),
        "collected_via": COLLECTED_VIA,
        "lang": (t.get("lang") or "fr")[:8],
        "word_count": len(text.split()),
        "quoted_handle": None, "quoted_url": None, "quoted_content": None,  # jeu de clés constant
    }
    if quote:
        q_author = (quote.get("author") or {}).get("screen_name")
        out["quoted_handle"] = q_author
        out["quoted_url"] = quote.get("url")
        out["quoted_content"] = (quote.get("text") or "")[:2000] or None
    return out


async def fetch_tweet(client: httpx.AsyncClient, handle: str, tid: str) -> dict | None:
    try:
        r = await client.get(FX_URL.format(handle=handle, tid=tid))
    except httpx.HTTPError as exc:
        logger.debug("backfill.fx_error", tid=tid, error=str(exc)[:100])
        return None
    if r.status_code != 200:
        return None  # 404 = tweet supprimé/privé : on n'insiste pas
    try:
        return _fx_to_post(r.json(), handle)
    except ValueError:
        return None


async def run_backfill(
    *, handles: list[str] | None = None, since_year: int = 2022,
    per_handle: int = 300, max_fetch: int = 2000,
) -> dict:
    """Remplit l'historique des handles donnés (ou de tout le pool actif)."""
    # Import tardif : x_collector importe x_syndication ; on évite tout cycle.
    from src.services.collection.x_collector import _insert_new  # noqa: PLC0415

    s = get_settings()
    factory = get_session_factory()
    async with factory() as db:
        q = select(Personality).where(Personality.is_active.is_(True), Personality.handle.isnot(None))
        if handles:
            # Les handles X sont insensibles à la casse (@SebChenu == @sebchenu).
            q = q.where(func.lower(Personality.handle).in_([h.lower() for h in handles]))
        people = list((await db.execute(q)).scalars().all())
        known = set(
            _STATUS_RE.search(u).group(1)
            for u in (await db.execute(select(Post.url))).scalars().all()
            if _STATUS_RE.search(u or "")
        )

    fetched = inserted = 0
    per_handle_stats: dict[str, int] = {}
    headers = {"User-Agent": s.user_agent, "Accept": "application/json"}
    async with httpx.AsyncClient(timeout=s.request_timeout_seconds, headers=headers,
                                 follow_redirects=True) as client:
        for p in people:
            if fetched >= max_fetch:
                break
            ids = await list_archived_ids(client, p.handle, since_year=since_year, limit=per_handle)
            todo = [i for i in ids if i not in known]
            posts: list[dict] = []
            for tid in todo:
                if fetched >= max_fetch:
                    break
                d = await fetch_tweet(client, p.handle, tid)
                fetched += 1
                if d:
                    posts.append(d)
                    known.add(tid)
                await asyncio.sleep(s.request_delay_seconds)
            if posts:
                async with factory() as db:
                    n = await _insert_new(db, p.id, posts)
                inserted += n
                per_handle_stats[p.handle] = n
            logger.info("backfill.handle", handle=p.handle, archived=len(ids),
                        new_ids=len(todo), inserted=len(posts))

    stats = {"handles": len(people), "fetched": fetched, "inserted": inserted,
             "since_year": since_year, "per_handle": per_handle_stats}
    logger.info("backfill.done", **{k: v for k, v in stats.items() if k != "per_handle"})
    return stats
