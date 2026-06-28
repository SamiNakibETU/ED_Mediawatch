"""Archivage / « reçus » — preuve traçable des prises de parole.

Pour la presse ET X : on conserve une copie même si l'article/le tweet est
supprimé ou passe en paywall. Deux couches complémentaires :

  * **snapshot HTML local** (`data/snapshots/...`) — immédiat, sans infra,
    garantit une copie qu'on possède.
  * **archive externe citable** — par défaut **Wayback** (archive.org Save Page
    Now : URL publique pérenne, sans infra). Backend enfichable :
    `archivebox` (self-host, repris de la branche v2/media-watch) plus tard.

Conçu comme une passe **résumable** : on n'archive que les lignes non encore
archivées, avec rate-limiting (Wayback est lent et limité).
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import aiohttp
import structlog
from sqlalchemy import select

from src.config import get_settings
from src.database import get_session_factory
from src.models.article import Article
from src.models.post import Post
from urllib.parse import urlparse

from src.services.archive.archivebox_client import get_archivebox_client
from src.services.archive.wayback_availability import (
    fetch_wayback_availability,
    save_page_now,
)
from src.utils import sha256

logger = structlog.get_logger(__name__)

_MODELS = {"press": Article, "x": Post}


def _archive_target(kind: str, url: str) -> str:
    """URL à archiver. Pour X, on canonicalise vers x.com (le lien Nitter pointe
    une instance éphémère qui s'archive mal et peut disparaître)."""
    if kind == "x":
        path = urlparse(url).path  # /J_Bardella/status/123
        if "/status/" in path:
            return f"https://x.com{path}"
    return url


async def _save_local_html(url: str, kind: str, ua: str, timeout: int) -> str | None:
    settings = get_settings()
    out_dir = settings.snapshot_path_dir / kind
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{sha256(url)}.html"
    if path.exists():
        return str(path)
    try:
        async with aiohttp.ClientSession(headers={"User-Agent": ua}) as http:
            async with http.get(
                url, timeout=aiohttp.ClientTimeout(total=timeout), allow_redirects=True
            ) as resp:
                if resp.status != 200:
                    return None
                html = await resp.text()
        path.write_text(html, encoding="utf-8", errors="ignore")
        return str(path)
    except Exception as exc:  # noqa: BLE001
        logger.debug("archive.local_fail", url=url, error=str(exc)[:120])
        return None


async def run_archival(kind: str = "press", limit: int = 100) -> dict:
    """Archive up to `limit` not-yet-archived items of `kind` ('press'|'x')."""
    settings = get_settings()
    if settings.archive_backend == "none":
        return {"archived": 0, "skipped": "backend=none"}

    model = _MODELS[kind]
    factory = get_session_factory()
    ua = settings.user_agent
    timeout = settings.request_timeout_seconds

    async with factory() as db:
        rows = list(
            (
                await db.execute(
                    select(model)
                    .where(model.archived_at.is_(None))
                    .order_by(model.id.desc())
                    .limit(limit)
                )
            ).scalars().all()
        )

    abox = get_archivebox_client() if settings.archive_backend == "archivebox" else None

    archived = failed = created = 0
    for row in rows:
        target = _archive_target(kind, row.url)
        # 1) copie locale qu'on possède — utile pour la presse (HTML statique).
        #    Inutile pour X (x.com = appli JS + login wall) → on s'appuie sur Wayback.
        #    ⚠️ FS Railway éphémère : la copie locale ne survit pas à un redeploy ;
        #    le reçu DURABLE est l'URL Wayback ci-dessous.
        snapshot_path = (
            await _save_local_html(target, kind, ua, timeout) if kind == "press" else None
        )

        # 2) archive externe selon le backend
        snapshot_url: str | None = None
        slow = False
        if settings.archive_backend == "wayback":
            # a) lien vers une capture existante (rapide)
            avail = await fetch_wayback_availability(target)
            snapshot_url = avail.get("closest_url")
            # b) sinon on en CRÉE une (Save Page Now) — sinon un item frais n'a
            #    aucun reçu. Lent + rate-limité → réservé aux items sans capture.
            if not snapshot_url and settings.wayback_save_enabled:
                slow = True
                created_url = await save_page_now(target)
                if created_url:
                    snapshot_url = created_url
                    created += 1
        elif settings.archive_backend == "archivebox" and abox is not None:
            result = await abox.archive(target, tags=[kind])
            if result:
                snapshot_url = result.get("snapshot", {}).get("timestamp") or "archivebox"

        async with factory() as db:
            obj = await db.get(model, row.id)
            if obj:
                obj.snapshot_path = snapshot_path
                obj.snapshot_url = snapshot_url
                # On ne marque archivé QUE si on a un reçu durable (Wayback/ArchiveBox)
                # ou une copie locale ; sinon on retentera au prochain passage.
                if snapshot_path or snapshot_url:
                    obj.archived_at = datetime.now(timezone.utc)
                await db.commit()

        if snapshot_path or snapshot_url:
            archived += 1
        else:
            failed += 1
        # SPN est lent et rate-limité → délai plus long quand on a créé une capture.
        await asyncio.sleep(
            settings.archive_save_rate_seconds if slow else settings.archive_rate_seconds
        )

    stats = {"kind": kind, "considered": len(rows), "archived": archived,
             "created": created, "failed": failed}
    logger.info("archive.done", **stats)
    return stats
