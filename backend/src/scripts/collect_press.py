"""Lance une passe de collecte presse — pratique via railway ssh.

    railway ssh "python -m src.scripts.collect_press"          # incrémental (ajoute le neuf)
    railway ssh "python -m src.scripts.collect_press --reset"  # purge + recollecte tout
                                                               # (applique mentions+PDP + Jina)
"""

import asyncio
import sys

from src.services.collection.press_collector import run_press_collection


async def main() -> None:
    reset = "--reset" in sys.argv
    stats = await run_press_collection(reset=reset)
    stats["errors"] = len(stats["errors"])
    print("collecte presse:", stats)


if __name__ == "__main__":
    asyncio.run(main())
