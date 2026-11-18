"""Ramène en base les décisions prises par les relecteurs sur le site en ligne.

Chaque décision attend dans l'espace KV ``DECISIONS`` (``infra/pages/functions/decision.js``).
Ici, on les lit toutes, on archive chacune une fois dans ``donnees/decisions/decisions.ndjson``
(avec le nom du relecteur, sa date, son motif), et on applique la plus récente de chaque écart,
si elle est plus récente que ce que la base contient. Rien n'est effacé du KV : l'historique
reste des deux côtés.

    python -m src.scripts.rapatrier_decisions
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime
from pathlib import Path

ETUDE = Path(__file__).resolve().parents[4]
ARCHIVE = ETUDE / "donnees" / "decisions" / "decisions.ndjson"


def lire_kv() -> list[dict]:
    from src.scripts.publier_site import CONF, wrangler
    import re

    m = re.search(r'id\s*=\s*"([0-9a-f]{32})"', CONF.read_text(encoding="utf-8"))
    if not m:
        return []
    ns = m.group(1)
    cles = [k["name"] for k in json.loads(wrangler("kv", "key", "list", "--namespace-id", ns, "--remote"))]
    deja = set()
    if ARCHIVE.exists():
        deja = {json.loads(l)["cle"] for l in ARCHIVE.read_text(encoding="utf-8").splitlines() if l.strip()}
    nouvelles = []
    for c in cles:
        if c in deja:
            continue
        d = json.loads(wrangler("kv", "key", "get", c, "--namespace-id", ns, "--remote"))
        d["cle"] = c
        nouvelles.append(d)
    if nouvelles:
        ARCHIVE.parent.mkdir(parents=True, exist_ok=True)
        with ARCHIVE.open("a", encoding="utf-8") as f:
            for d in nouvelles:
                f.write(json.dumps(d, ensure_ascii=False) + "\n")
    return nouvelles


async def appliquer(decisions: list[dict]) -> int:
    from src.database import get_session_factory, init_db
    from src.models.ecart import STATUTS, Ecart

    await init_db()
    derniere: dict[int, dict] = {}
    for d in sorted(decisions, key=lambda d: d["quand"]):
        if d.get("statut") in STATUTS:
            derniere[int(d["ecart"])] = d
    n = 0
    async with get_session_factory()() as db:
        for ecart_id, d in derniere.items():
            e = await db.get(Ecart, ecart_id)
            quand = datetime.fromisoformat(d["quand"].replace("Z", "+00:00"))
            if e is None or (e.decided_at and e.decided_at.replace(tzinfo=quand.tzinfo) >= quand):
                continue
            e.statut = d["statut"]
            e.decision_note = f"[{d['relecteur']}] {d.get('note') or ''}".strip()
            e.decided_at = quand
            n += 1
        await db.commit()
    return n


def rapatrier() -> dict:
    nouvelles = lire_kv()
    return {"decisions_nouvelles": len(nouvelles), "appliquees": asyncio.run(appliquer(nouvelles)) if nouvelles else 0}


if __name__ == "__main__":
    print(rapatrier())
