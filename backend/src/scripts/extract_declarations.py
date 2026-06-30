"""L0 — remplit le Grand Livre : segmente posts/articles en déclarations (tous types).

    python -m src.scripts.extract_declarations                 # défauts (500 posts / 300 articles)
    python -m src.scripts.extract_declarations 1000 500        # limites custom

Pré-requis : une clé du provider tier-2 (CEREBRAS_API_KEY par défaut). Sans clé,
rien n'est créé (on ne fabrique pas de substrat). Idempotent (rejouable).
"""

from __future__ import annotations

import asyncio
import sys

from src.services.analysis.declaration_extractor import run_declaration_extraction


def _arg(i: int, default: int) -> int:
    try:
        return int(sys.argv[i])
    except (IndexError, ValueError):
        return default


if __name__ == "__main__":
    stats = asyncio.run(
        run_declaration_extraction(
            limit_posts=_arg(1, 500), limit_articles=_arg(2, 300)
        )
    )
    print(f"Grand Livre — extraction de déclarations : {stats}")
