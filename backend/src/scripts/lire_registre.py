"""Lit le corpus X dans le registre des déclarations, par l'abonnement ChatGPT (Codex CLI).

Ordre de lecture : d'abord les tweets qui touchent un enjeu du référentiel (repérés par
les mots-clés de ``atelier_enjeux.MOTS``), puis, avec ``--tout``, le reste, pour les
déclarations hors liste. Le repérage ne décide de rien : il fixe l'ordre. Le filtre du
registre relit chaque tweet.

Chaque passe est reprenable : un tweet lu porte sa marque (``decl_lu``), un appel raté
ne marque rien. Un refus de Codex (quota de l'abonnement) arrête la passe proprement ;
la relancer plus tard reprend où elle s'était arrêtée.

    python -m src.scripts.lire_registre --essai          # combien à lire
    python -m src.scripts.lire_registre --limit 200      # un essai réel
    python -m src.scripts.lire_registre                  # tous les tweets à enjeu
    python -m src.scripts.lire_registre --tout           # puis le reste
"""

from __future__ import annotations

import argparse
import asyncio
import os
import re
import time

TRANCHE = 2000


def _fournisseur_codex() -> None:
    # Avant tout import de la configuration : elle est mise en cache au premier appel.
    os.environ.setdefault("CLAIM_TIER1_PROVIDER", "codex")
    os.environ.setdefault("CLAIM_TIER2_PROVIDER", "codex")


async def a_lire(tout: bool) -> list[int]:
    from sqlalchemy import or_, select

    from src.database import get_session_factory, init_db
    from src.models.post import Post
    from src.scripts.atelier_enjeux import MOTS
    from src.services.analysis.registre import VERSION

    await init_db()
    motif = re.compile("|".join(f"(?:{m})" for m in MOTS.values()), re.IGNORECASE)
    async with get_session_factory()() as db:
        rows = (await db.execute(
            select(Post.id, Post.content).where(or_(Post.decl_lu.is_(None), ~Post.decl_lu.startswith(VERSION)))
            .order_by(Post.published_at.desc().nullslast())
        )).all()
    touche = [i for i, c in rows if c and motif.search(c)]
    if not tout:
        return touche
    vus = set(touche)
    return touche + [i for i, _ in rows if i not in vus]


async def passer(ids: list[int], limit: int | None) -> dict:
    from src.services.analysis.llm_usage import ProviderRefused
    from src.services.analysis.registre import lire

    ids = ids[:limit] if limit else ids
    total: dict = {}
    debut = time.monotonic()
    for i in range(0, len(ids), TRANCHE):
        tranche = ids[i:i + TRANCHE]
        try:
            s = await lire(ids=tranche, limit=len(tranche), plus_recents=True)
        except ProviderRefused as exc:
            print(f"Arrêt : {exc}. Relancer plus tard reprend où on en est.", flush=True)
            total["arret"] = str(exc)[:200]
            break
        for k, v in s.items():
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                total[k] = total.get(k, 0) + v
        fait = min(i + TRANCHE, len(ids))
        print(f"{fait}/{len(ids)} tweets passés en {(time.monotonic() - debut) / 60:.0f} min : "
              f"{total.get('declarations', 0)} déclarations, {total.get('echecs', 0)} échecs", flush=True)
        if s.get("budget_atteint"):
            break
    return total


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--essai", action="store_true", help="compter sans lire")
    p.add_argument("--tout", action="store_true", help="aussi les tweets sans mot-clé d'enjeu")
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--fournisseur", default="codex", help="codex (abonnement) ou openrouter (clé)")
    a = p.parse_args()
    if a.fournisseur == "codex":
        _fournisseur_codex()
    ids = asyncio.run(a_lire(a.tout))
    print(f"{len(ids)} tweets à lire", flush=True)
    if not a.essai:
        print(asyncio.run(passer(ids, a.limit)), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
