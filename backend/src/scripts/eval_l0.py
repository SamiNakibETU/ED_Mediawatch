"""Évaluation du L0 : export à annoter, puis calcul précision/rappel.

    python -m src.scripts.eval_l0 export [N]           # CSV à annoter (data/eval/)
    python -m src.scripts.eval_l0 score decl.csv [sources.csv]

Protocole (phase 1) : ~200 déclarations annotées (label 1/0) + le décompte des
assertions ratées par source (missed) → précision et rappel estimé, par type.
Cible avant d'ouvrir aux 168 figures : précision ≥ 0,9 sur le pilote.
"""

from __future__ import annotations

import asyncio
import json
import sys

from src.services.analysis.l0_eval import export_for_annotation, score

if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "export"
    if cmd == "export":
        n = int(sys.argv[2]) if len(sys.argv) > 2 else 250
        out = asyncio.run(export_for_annotation(limit=n))
    elif cmd == "score":
        if len(sys.argv) < 3:
            sys.exit("usage : eval_l0 score declarations.csv [sources.csv]")
        out = score(sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else None)
    else:
        sys.exit(f"commande inconnue : {cmd} (export | score)")
    print(json.dumps(out, ensure_ascii=False, indent=2))
