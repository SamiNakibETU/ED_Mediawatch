"""Client ArchiveBox — archivage possédé multi-format (HTML/PDF/screenshot/WARC).

Repris de breve_de_presse_PMO (branche v2/media-watch), adapté à la config
ED_Mediawatch. C'est la couche « reçus » de référence : une copie qu'on possède,
opposable, même si la source est supprimée ou paywallée. Opt-in
(`ARCHIVEBOX_ENABLED=true`) car nécessite ArchiveBox installé (Docker ou pip).
"""

from __future__ import annotations

import asyncio
import json
import shlex
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import structlog

from src.config import get_settings

logger = structlog.get_logger(__name__)


class ArchiveBoxClient:
    def __init__(self) -> None:
        s = get_settings()
        self.data_dir = Path(s.archivebox_data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self._cmd = shlex.split(s.archivebox_binary)
        self._initialized = False

    def _run(self, args: list[str], timeout: int) -> subprocess.CompletedProcess:
        return subprocess.run(
            [*self._cmd, *args],
            cwd=self.data_dir,
            capture_output=True,
            text=True,
            timeout=timeout,
        )

    async def init_archive(self) -> bool:
        try:
            result = await asyncio.to_thread(self._run, ["init", "--install"], 180)
            self._initialized = result.returncode == 0
            if not self._initialized:
                logger.warning("archivebox.init_failed", stderr=result.stderr[:300])
            return self._initialized
        except FileNotFoundError:
            logger.error("archivebox.binary_not_found", binary=self._cmd)
            return False
        except Exception as exc:  # noqa: BLE001
            logger.error("archivebox.init_error", error=str(exc)[:200])
            return False

    async def archive(self, url: str, tags: list[str] | None = None) -> dict[str, Any] | None:
        """Archive une URL dans tous les formats. Retourne le snapshot info ou None."""
        if not self._initialized and not await self.init_archive():
            return None
        extractors = ["title", "article", "pdf", "screenshot", "singlefile", "warc"]
        tags = (tags or []) + ["ed_mediawatch"]
        try:
            result = await asyncio.to_thread(
                self._run,
                ["add", url, "--depth=0", "--extract", ",".join(extractors),
                 "--tag", ",".join(tags)],
                300,
            )
            if result.returncode != 0:
                logger.warning("archivebox.add_failed", url=url[:80], stderr=result.stderr[:300])
                return None
            snapshot = await self._snapshot_info(url)
            return {
                "url": url,
                "archived_at": datetime.now(timezone.utc).isoformat(),
                "snapshot": snapshot,
            }
        except subprocess.TimeoutExpired:
            logger.error("archivebox.timeout", url=url[:80])
            return None
        except Exception as exc:  # noqa: BLE001
            logger.error("archivebox.archive_error", url=url[:80], error=str(exc)[:200])
            return None

    async def _snapshot_info(self, url: str) -> dict[str, Any]:
        try:
            result = await asyncio.to_thread(self._run, ["list", url, "--json"], 30)
            if result.returncode == 0 and result.stdout:
                for line in result.stdout.strip().split("\n"):
                    if not line.strip():
                        continue
                    try:
                        data = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if data.get("url") == url:
                        return {
                            "timestamp": data.get("timestamp"),
                            "paths": data.get("archive_path", {}),
                        }
        except Exception as exc:  # noqa: BLE001
            logger.debug("archivebox.snapshot_info_error", error=str(exc)[:120])
        return {}


_client: ArchiveBoxClient | None = None


def get_archivebox_client() -> ArchiveBoxClient:
    global _client
    if _client is None:
        _client = ArchiveBoxClient()
    return _client
