"""Garde par jeton pour les endpoints coûteux (collecte, LLM, archivage).

Si `API_TOKEN` est défini (prod), ces routes exigent l'en-tête `X-API-Token`.
Sinon (dev local), elles restent ouvertes. Les routes en lecture seule (GET) et
la validation humaine ne sont pas gardées.
"""

from fastapi import Header, HTTPException

from src.config import get_settings


async def require_token(x_api_token: str | None = Header(default=None)) -> None:
    token = get_settings().api_token
    if token and x_api_token != token:
        raise HTTPException(status_code=401, detail="X-API-Token manquant ou invalide")
