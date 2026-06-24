"""Lance une passe de classification thématique CAP — pratique via railway ssh.

    railway ssh "python -m src.scripts.classify"           # tout, Cohere auto
    railway ssh "python -m src.scripts.classify --reset"   # reclasse même les classés
    railway ssh "python -m src.scripts.classify --press"   # presse seule
    railway ssh "python -m src.scripts.classify --no-cohere"  # déterministe seul
"""

import asyncio
import sys

from src.services.classification.runner import classify_all


async def main() -> None:
    argv = sys.argv[1:]
    kind = "press" if "--press" in argv else ("x" if "--x" in argv else "all")
    reset = "--reset" in argv
    use_cohere = False if "--no-cohere" in argv else None  # None = auto
    stats = await classify_all(kind=kind, reset=reset, use_cohere=use_cohere)
    print("classification:", stats)


if __name__ == "__main__":
    asyncio.run(main())
