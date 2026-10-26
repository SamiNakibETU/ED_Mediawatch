"""Import des captures Zeeschuimer : les tweets que X a montrés à un navigateur connecté.

Zeeschuimer (Digital Methods Initiative, université d'Amsterdam) enregistre les
réponses GraphQL que reçoit le client web de X pendant qu'une personne navigue.
C'est la seule source complète : une recherche X sur un compte et une période
rend tous ses tweets, là où la syndication n'en montre que les derniers et
Wayback une partie seulement.

La lecture reprend le parseur calibré pour l'étude IRIS sur un export réel du
5 octobre 2026 (Zeeschuimer 1.14.3) : l'auteur n'a plus de bloc `legacy`, son
identifiant est sous `core` ; le texte long d'un « note tweet » est à part.

Seuls les tweets des comptes suivis entrent en base, y compris quand ils
apparaissent cités ou retweetés par un autre compte. Le format écrit est celui
de la collecte habituelle, avec la même clé de dédoublonnage : un tweet déjà
collecté par la syndication n'est pas dupliqué.
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import Any

import structlog
from sqlalchemy import select

from src.database import get_session_factory
from src.models.personality import Personality
from src.utils import tweet_guid

logger = structlog.get_logger(__name__)

COLLECTED_VIA = "zeesch"  # ≤ 8 car. (Post.collected_via)
_DATE_FMT = "%a %b %d %H:%M:%S %z %Y"


def _dig(obj: Any, *path) -> Any:
    for key in path:
        if not isinstance(obj, dict):
            return None
        obj = obj.get(key)
    return obj


def _node(item: Any) -> dict | None:
    """L'objet tweet qui porte `legacy`, où que la capture l'ait rangé."""
    if not isinstance(item, dict):
        return None
    for path in ((), ("tweet",), ("result",), ("result", "tweet"),
                 ("tweet_results", "result"), ("tweet_results", "result", "tweet")):
        node = _dig(item, *path) if path else item
        legacy = node.get("legacy") if isinstance(node, dict) else None
        if isinstance(legacy, dict) and legacy.get("full_text"):
            return node
    return None


def _auteur(node: dict) -> str | None:
    user = _dig(node, "core", "user_results", "result") or {}
    return (_dig(user, "core", "screen_name") or _dig(user, "legacy", "screen_name")
            or _dig(node, "legacy", "user", "screen_name"))


def _texte(node: dict) -> str:
    note = _dig(node, "note_tweet", "note_tweet_results", "result")
    if isinstance(note, dict) and note.get("text"):
        texte, entites = note["text"], note.get("entity_set") or {}
    else:
        texte, entites = node["legacy"].get("full_text") or "", node["legacy"].get("entities") or {}
    for u in entites.get("urls") or []:
        if u.get("url") and u.get("expanded_url"):
            texte = texte.replace(u["url"], u["expanded_url"])
    return texte.strip()


def _date(raw: Any) -> datetime | None:
    try:
        return datetime.strptime(raw, _DATE_FMT).astimezone(timezone.utc) if raw else None
    except (TypeError, ValueError):
        return None


def tweet(node: dict) -> tuple[str, dict] | None:
    """(auteur, dict au format de la collecte) pour un objet tweet GraphQL."""
    legacy = node["legacy"]
    tid = legacy.get("id_str") or node.get("rest_id")
    auteur = _auteur(node)
    if not tid or not auteur:
        return None
    retweete = _node(_dig(legacy, "retweeted_status_result")) or _node(_dig(node, "retweeted_status_result"))
    cite = _node(_dig(node, "quoted_status_result"))
    corps = retweete or node
    texte = _texte(corps)
    if not texte:
        return None
    reponse_a = legacy.get("in_reply_to_screen_name")
    url = f"https://x.com/{auteur}/status/{tid}"
    propre = retweete is None  # un retweet n'a pas d'engagement à lui
    out = {
        "guid": tweet_guid(auteur, url), "url": url, "content": texte,
        "published_at": _date(legacy.get("created_at")),
        "is_retweet": retweete is not None, "is_reply": bool(reponse_a),
        "post_type": ("retweet" if retweete else "quote" if cite else "reply" if reponse_a else "original"),
        "reply_to_handle": reponse_a,
        "reply_to_url": (f"https://x.com/{reponse_a}/status/{legacy['in_reply_to_status_id_str']}"
                         if reponse_a and legacy.get("in_reply_to_status_id_str") else None),
        "likes": legacy.get("favorite_count") if propre else None,
        "retweets": legacy.get("retweet_count") if propre else None,
        "replies": legacy.get("reply_count") if propre else None,
        "quotes": legacy.get("quote_count") if propre else None,
        "lang": (legacy.get("lang") or "fr")[:8],
        "text_truncated": False, "collected_via": COLLECTED_VIA,
    }
    vues = _dig(node, "views", "count")
    if propre and vues:
        try:
            out["views"] = int(vues)
        except (TypeError, ValueError):
            pass
    porte = cite or retweete
    if porte is not None:
        a_porte = _auteur(porte)
        t_id = porte["legacy"].get("id_str") or porte.get("rest_id")
        out["quoted_handle"] = a_porte
        out["quoted_url"] = f"https://x.com/{a_porte}/status/{t_id}" if a_porte and t_id else None
        if cite is not None:
            out["quoted_content"] = _texte(cite)[:2000] or None
    out["word_count"] = len(texte.split())
    return auteur, out


def lire(texte: str) -> tuple[list[tuple[str, dict]], int]:
    """Tous les tweets d'un export NDJSON, avec ceux qu'ils citent ou retweetent."""
    tweets: list[tuple[str, dict]] = []
    illisibles = 0
    # Découpe sur le saut de ligne seul : un tweet peut contenir U+2028.
    for ligne in texte.split("\n"):
        ligne = ligne.strip()
        if not ligne:
            continue
        try:
            enveloppe = json.loads(ligne)
        except ValueError:
            illisibles += 1
            continue
        item = enveloppe.get("data") if isinstance(enveloppe.get("data"), dict) else enveloppe
        node = _node(item)
        if node is None:
            illisibles += 1
            continue
        for n in (node, _node(_dig(node, "quoted_status_result")),
                  _node(_dig(node, "legacy", "retweeted_status_result")),
                  _node(_dig(node, "retweeted_status_result"))):
            if n is not None and (t := tweet(n)):
                tweets.append(t)
    return tweets, illisibles


async def importer(texte: str) -> dict:
    """Écrit en base les tweets des comptes suivis contenus dans un export."""
    tweets, illisibles = lire(texte)
    return await importer_lot(tweets, illisibles)


# Ce qu'un lot venu d'ailleurs peut écrire dans `posts` : rien d'autre ne passe.
CHAMPS_LOT = {"url", "content", "published_at", "is_retweet", "is_reply", "post_type", "reply_to_handle",
              "reply_to_url", "likes", "retweets", "replies", "quotes", "views", "lang", "text_truncated",
              "collected_via", "quoted_handle", "quoted_url", "quoted_content", "word_count"}


def normaliser_lot(brut: list[dict], via: str) -> list[tuple[str, dict]]:
    """Un lot JSON (un objet par tweet, avec `auteur`) au format de `importer_lot`.

    Les champs hors liste sont ignorés, la date ISO redevient une date, l'adresse
    doit être celle d'un tweet sur x.com : un lot ne peut pas écrire n'importe quoi.
    """
    out = []
    for t in brut:
        auteur, url = str(t.get("auteur") or ""), str(t.get("url") or "")
        if not auteur or not url.startswith("https://x.com/") or not t.get("content"):
            continue
        d = {k: v for k, v in t.items() if k in CHAMPS_LOT}
        if isinstance(d.get("published_at"), str):
            try:
                d["published_at"] = datetime.fromisoformat(d["published_at"]).astimezone(timezone.utc)
            except ValueError:
                d["published_at"] = None
        d["collected_via"] = via[:8]
        # Mêmes champs pour tous : un INSERT multi-lignes aux clés hétérogènes
        # fait échouer le lot entier (vu en août 2026 sur les `quoted_*`).
        for k in CHAMPS_LOT:
            d.setdefault(k, False if k in ("is_retweet", "is_reply", "text_truncated")
                         else 0 if k == "word_count" else None)
        out.append((auteur, d))
    return out


async def importer_lot(tweets: list[tuple[str, dict]], illisibles: int = 0) -> dict:
    """Écrit en base les tweets des comptes suivis, sans doublon avec les autres voies."""
    from src.services.collection.x_collector import _insert_new

    factory = get_session_factory()
    async with factory() as db:
        suivis = {h.lower(): (pid, h) for pid, h in (await db.execute(
            select(Personality.id, Personality.handle).where(Personality.handle.isnot(None)))).all()}
    par_figure: dict[int, dict[str, dict]] = defaultdict(dict)
    hors_panel: Counter = Counter()
    for auteur, d in tweets:
        cible = suivis.get(auteur.lower())
        if cible is None:
            hors_panel[auteur] += 1
            continue
        pid, handle = cible
        d["guid"] = tweet_guid(handle, d["url"])  # même clé que la syndication
        par_figure[pid][d["guid"]] = d
    inseres = 0
    detail = {}
    for pid, posts in par_figure.items():
        async with factory() as db:
            n = await _insert_new(db, pid, list(posts.values()))
        inseres += n
        detail[pid] = {"lus": len(posts), "nouveaux": n}
    stats = {"tweets_lus": len(tweets), "lignes_illisibles": illisibles,
             "figures": len(par_figure), "nouveaux": inseres,
             "hors_panel": sum(hors_panel.values()), "par_figure": detail}
    logger.info("zeeschuimer.import", **{k: v for k, v in stats.items() if k != "par_figure"})
    return stats
