"""Métadonnées de l'API exposées au front (vocabulaire contrôlé).

Le front récupère ici les valeurs d'énumération (nature, leaning, group_code…)
au lieu de les recopier en dur, pour rester aligné sur le back sans drift.
"""

from fastapi import APIRouter

from src.vocabulary import as_dict

router = APIRouter(tags=["meta"])


@router.get("/vocabulary")
async def vocabulary() -> dict:
    """Vocabulaire contrôlé (source unique de vérité, cf. `src/vocabulary.py`)."""
    return as_dict()
