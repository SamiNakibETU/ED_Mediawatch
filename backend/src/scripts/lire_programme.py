"""Lit les livrets PDF d'un programme et écrit `data/programme/<source>.json`.

    python -m src.scripts.lire_programme <dossier_pdf> --source rn-2022 --parti RN \
        --annee 2022 --titre "M la France, présidentielle 2022"

À lancer sur un poste, une fois par programme : la production ne lit pas de PDF,
elle charge le fichier produit ici (voir `services/analysis/programme.py`).
Les livrets déjà présents dans le fichier sont gardés : relancer ne relit que
les nouveaux. `--tout` relit tout.
"""

import argparse
import asyncio
import json
from pathlib import Path

from src.services.analysis.claim_llm import get_claim_llm
from src.services.analysis.programme import DATA_DIR, entete, lire_livret


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("dossier")
    ap.add_argument("--source", required=True)
    ap.add_argument("--parti", required=True)
    ap.add_argument("--annee", type=int, required=True)
    ap.add_argument("--titre", required=True)
    ap.add_argument("--tout", action="store_true")
    a = ap.parse_args()

    sortie = DATA_DIR / f"{a.source}.json"
    deja = json.loads(sortie.read_text(encoding="utf-8")) if sortie.exists() and not a.tout else None
    engagements = deja["engagements"] if deja else []
    lus = {e["livret"] for e in engagements}

    llm = get_claim_llm()
    sem = asyncio.Semaphore(4)

    async def un(pdf: Path) -> list[dict]:
        async with sem:
            try:
                r = await lire_livret(llm, pdf)
                print(f"{pdf.stem} : {len(r)} engagements", flush=True)
                return r
            except Exception as exc:  # noqa: BLE001
                print(f"{pdf.stem} : échec ({str(exc)[:120]})", flush=True)
                return []

    nouveaux = [p for p in sorted(Path(a.dossier).glob("*.pdf")) if p.stem not in lus]
    for r in await asyncio.gather(*(un(p) for p in nouveaux)):
        engagements += r

    doc = entete(a.source, a.parti, a.annee, a.titre,
                 lecteur=f"{llm.model_for(2)} (raisonnement court)")
    doc["livrets"] = sorted({e["livret"] for e in engagements})
    doc["engagements"] = sorted(engagements, key=lambda e: (e["livret"], e.get("page") or 0))
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    sortie.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{len(doc['engagements'])} engagements, {len(doc['livrets'])} livrets -> {sortie}")


if __name__ == "__main__":
    asyncio.run(main())
