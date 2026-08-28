"""Diagnostic de configuration : le système peut-il travailler, et jusqu'où ?

Répond en une commande à « pourquoi rien ne sort ». Chaque ligne dit ce qui est
en place, ce qui manque, et ce que l'absence empêche exactement — plutôt que de
laisser deviner quelle variable oubliée bloque quelle étape.

    railway ssh "python -m src.scripts.diag_config"

Ne révèle jamais une clé : seulement sa présence et son préfixe.
"""

import asyncio

from src.config import get_settings


def _mask(value: str | None) -> str:
    if not value:
        return "ABSENTE"
    return f"présente ({value[:7]}…, {len(value)} car.)"


async def main() -> None:
    s = get_settings()

    print("\n── Base de données ──")
    url = s.database_url
    kind = "PostgreSQL" if "postgres" in url else "SQLite (local)"
    print(f"  moteur                : {kind}")

    print("\n── Clés ──")
    print(f"  OPENROUTER_API_KEY    : {_mask(s.openrouter_api_key)}")
    print(f"  COHERE_API_KEY        : {_mask(s.cohere_api_key)}")
    print(f"  API_TOKEN             : {_mask(s.api_token)}")

    print("\n── Extraction ──")
    print(f"  LLM_REFINE_ENABLED    : {s.llm_refine_enabled}")
    print(f"  tier 1 (filtrage)     : {s.claim_tier1_provider} / {s.claim_tier1_model}")
    print(f"  tier 2 (structuré)    : {s.claim_tier2_provider} / {s.claim_tier2_model}")
    pilot = s.l0_pilot_handle_list
    print(f"  L0_PILOT_HANDLES      : {', '.join(pilot) if pilot else 'aucun (tout le pool)'}")

    print("\n── Budget ──")
    print(f"  plafond journalier    : {s.llm_daily_budget_usd} $")
    print(f"  plafond mensuel       : {s.llm_monthly_budget_usd} $")

    # Ce qui bloquerait, et ce que ça empêche précisément.
    blockers: list[str] = []
    if not s.llm_refine_enabled:
        blockers.append(
            "LLM_REFINE_ENABLED=false → aucune déclaration n'est extraite. "
            "Sans déclarations : pas de sujets, pas de contradictions."
        )
    if not s.openrouter_api_key:
        blockers.append(
            "OPENROUTER_API_KEY absente → extraction, nommage et juge inertes."
        )
    if not s.cohere_api_key and "postgres" in url:
        blockers.append(
            "COHERE_API_KEY absente en production → pas d'embeddings, donc pas "
            "de regroupement en sujets (le repli local n'est pas installé sur Railway)."
        )
    if s.llm_daily_budget_usd <= 0 and s.llm_monthly_budget_usd <= 0:
        blockers.append(
            "Aucun plafond de dépense armé → une passe peut coûter sans limite."
        )

    print("\n── Verdict ──")
    if blockers:
        for b in blockers:
            print(f"  BLOQUE  {b}")
    else:
        print("  Tout est en place : le pipeline peut tourner en scope=full.")
    print()


if __name__ == "__main__":
    asyncio.run(main())
