"""Lance le pipeline — une seule commande, l'ordre est dans le code.

    python -m src.scripts.pipeline                  # étapes gratuites
    python -m src.scripts.pipeline --full           # tout, y compris payant
    python -m src.scripts.pipeline judge            # cette étape + ses dépendances
    python -m src.scripts.pipeline --status         # l'entonnoir : où ça bloque
"""

import asyncio
import json
import sys

from src.database import init_db
from src.pipeline.runner import funnel, run_pipeline


async def main() -> None:
    await init_db()
    args = [a for a in sys.argv[1:]]
    if "--status" in args:
        print(json.dumps(await funnel(), indent=2, ensure_ascii=False, default=str))
        return
    scope = "full" if "--full" in args else "free"
    names = [a for a in args if not a.startswith("--")] or None
    rep = await run_pipeline(stages=names, scope=scope)
    print(f"\nRun #{rep['run_id']} — {rep['status']} · {rep['scope']} · ${rep['cost_usd']}")
    for s in rep["steps"]:
        mark = {"ok": "  ", "skipped": "· ", "failed": "!!", "budget_exceeded": "$$"}[s["status"]]
        print(f" {mark} {s['label']:44s} {s['status']:16s} {s['duration_s']:6.1f}s")
        if s["detail"]:
            print(f"      {s['detail']}")


if __name__ == "__main__":
    asyncio.run(main())
