"""Recalcule les écarts puis les fait vérifier, par l'abonnement ChatGPT (Codex CLI).

Trois temps, dans l'ordre de ``ecarts.py`` : détection (sans modèle), second avis sur chaque
déclaration qui crée un écart, puis les deux juges. Les écarts les plus amples passent d'abord.

Reprenable : un écart jugé porte sa décision (``auto``), une déclaration vérifiée sa marque.
Un refus de Codex (quota de l'abonnement) arrête la passe proprement.

    python -m src.scripts.juger_ecarts --essai         # détecter et compter, sans modèle
    python -m src.scripts.juger_ecarts --limit 40      # un essai réel
    python -m src.scripts.juger_ecarts                 # tout
"""

from __future__ import annotations

import argparse
import asyncio
import os
import time

TRANCHE = 40
# Les écarts de chiffre (deux nombres différents pour une même mesure) sont laissés de côté par
# défaut : le 18/11/2026, 11 sur 11 jugés étaient des faux écarts (un 76 % de sondage comparé à un
# taux de TVA de 5,5 %). La détection est à revoir avant de les juger : ``--types chiffre`` pour forcer.
TYPES = "temps,programme,parti"


def _fournisseur_codex(parallele: int) -> None:
    # Avant tout import de la configuration et du client Codex : lus une seule fois.
    os.environ.setdefault("CLAIM_TIER1_PROVIDER", "codex")
    os.environ.setdefault("CLAIM_TIER2_PROVIDER", "codex")
    os.environ.setdefault("CODEX_PARALLELE", str(parallele))
    # Second juge : un autre modèle de l'abonnement. Avec une clé OpenRouter valide, poser
    # JUGE2_MODEL=google/gemini-3.7-flash rend le juge d'une autre famille, comme prévu au départ.
    os.environ.setdefault("JUGE2_MODEL", "gpt-5.6-luna")


async def compter() -> dict:
    from sqlalchemy import func, select

    from src.database import get_session_factory
    from src.models.ecart import Ecart

    async with get_session_factory()() as db:
        rows = (await db.execute(select(Ecart.auto, func.count()).group_by(Ecart.auto))).all()
    return {a or "ouverts": n for a, n in rows}


async def passer(limit: int | None, parallele: int, essai: bool, types: tuple[str, ...] | None = None) -> dict:
    from src.database import init_db
    from src.services.analysis.ecarts import detecter, juger, second_avis
    from src.services.analysis.llm_usage import ProviderRefused

    await init_db()
    total: dict = {"detection": (await detecter())["total_nouveaux"]}
    print(f"{total['detection']} nouveaux écarts ; état : {await compter()}", flush=True)
    if essai:
        return total
    debut = time.monotonic()
    minutes = lambda: f"{(time.monotonic() - debut) / 60:.0f} min"

    async def boucle(nom: str, etape, cle: str) -> bool:
        """Répète ``etape`` par tranches tant qu'elle avance. Faux si Codex a refusé ou le budget est atteint."""
        fait = 0
        while limit is None or fait < limit:
            try:
                s = await etape(limit=min(TRANCHE, limit - fait) if limit else TRANCHE, parallele=parallele, types=types)
            except ProviderRefused as exc:
                print(f"Arrêt : {exc}. Relancer plus tard reprend où on en est.", flush=True)
                total["arret"] = str(exc)[:200]
                return False
            for k, v in s.items():
                if isinstance(v, int) and not isinstance(v, bool):
                    total[f"{nom}:{k}"] = total.get(f"{nom}:{k}", 0) + v
            fait += s[cle] + s["echecs"]
            print(f"{nom} : {fait} passés en {minutes()} ; {s}", flush=True)
            if s.get("budget_atteint"):
                return False
            if not s[cle]:      # plus rien à passer, ou que des échecs : ne pas tourner en rond
                break
        return True

    if await boucle("avis", second_avis, "verifiees"):
        await boucle("juges", juger, "juges")
    total["etat"] = await compter()
    return total


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--essai", action="store_true", help="détecter et compter sans appeler de modèle")
    p.add_argument("--limit", type=int, default=None, help="nombre de déclarations puis d'écarts à passer")
    p.add_argument("--parallele", type=int, default=4, help="appels de front")
    p.add_argument("--fournisseur", default="codex", help="codex (abonnement) ou openrouter (clé)")
    p.add_argument("--types", default=TYPES, help="types d'écarts à vérifier, séparés par des virgules")
    a = p.parse_args()
    if a.fournisseur == "codex":
        _fournisseur_codex(a.parallele)
    print(asyncio.run(passer(a.limit, a.parallele, a.essai, tuple(a.types.split(",")) if a.types else None)), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
