"""Déclenchement de la classification thématique (déterministe + Cohere fallback).

Lecture seule côté veille ; l'écriture des thèmes se fait par cette passe
(token requis). Pas de génération LLM — Cohere uniquement pour l'embedding.
"""

from fastapi import APIRouter, Depends, Query

from src.security import require_token
from src.services.classification.runner import classify_all

router = APIRouter(tags=["classification"])


@router.post("/classify", dependencies=[Depends(require_token)])
async def trigger_classify(
    kind: str = Query("all", description="x | press | all"),
    reset: bool = Query(False, description="reclasse même les items déjà classés"),
    use_cohere: bool | None = Query(
        None, description="None=auto (si clé Cohere) ; true/false pour forcer"
    ),
) -> dict:
    """Classe posts et/ou articles par thème/sous-thème CAP (idempotent)."""
    return await classify_all(kind=kind, reset=reset, use_cohere=use_cohere)
