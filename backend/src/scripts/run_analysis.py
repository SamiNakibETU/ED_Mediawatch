"""Orchestrateur de la passe d'ANALYSE — une seule commande.

Enchaîne, sur le corpus déjà collecté : nettoyage → extraction de claims →
embeddings → détection de contradictions. Idempotent (rejouable). Chaque étape
réutilise le service existant ; rien de neuf, juste l'enchaînement.

    python -m src.scripts.run_analysis                 # passe complète
    python -m src.scripts.run_analysis --no-llm        # extraction déterministe seule
    python -m src.scripts.run_analysis --reset-claims  # purge claims+contradictions d'abord

Pré-requis pour la qualité : LLM_REFINE_ENABLED=true + CEREBRAS_API_KEY (claims),
COHERE_API_KEY (embeddings). Sans clés : déterministe seul + embeddings sautés.
"""

from __future__ import annotations

import asyncio
import sys

import structlog

from src.scripts.clean_articles import run as clean_articles
from src.services.analysis.claim_embeddings import embed_claims
from src.services.analysis.claim_extractor import run_claim_extraction
from src.services.analysis.contradiction_detector import run_contradiction_detection
from src.services.analysis.enrich import enrich_claims

logger = structlog.get_logger(__name__)


async def run(use_llm: bool | None = None, reset_claims: bool = False) -> dict:
    # NB : l'extraction de DÉCLARATIONS (L0, LLM sur chaque post/article = coûteuse)
    # n'est PAS ici — elle se lance à part (`extract_declarations`). Ici : étapes
    # gratuites/cheap, rejouables sans surprise de coût.
    out: dict = {}
    out["clean"] = await clean_articles()
    out["claims"] = await run_claim_extraction(use_llm=use_llm, reset=reset_claims)
    out["embed"] = await embed_claims()
    out["enrich"] = await enrich_claims()  # L1 : thème + référent, zéro coût API
    out["contradictions"] = await run_contradiction_detection()
    logger.info("run_analysis.done", **{k: out[k] for k in out})
    print("=== Passe d'analyse terminée ===")
    for step, res in out.items():
        print(f"  {step}: {res}")
    return out


if __name__ == "__main__":
    args = sys.argv[1:]
    use_llm = False if "--no-llm" in args else None  # None = suit LLM_REFINE_ENABLED
    asyncio.run(run(use_llm=use_llm, reset_claims="--reset-claims" in args))
