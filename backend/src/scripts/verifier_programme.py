"""Second avis sur les engagements de programme : la position lue est-elle bien celle du passage ?

La lecture des programmes range chaque engagement sur l'échelle d'un enjeu. Elle se trompe parfois
(« hausse des salaires de 10 % avec accord d'entreprises » rangé sous « augmenter le SMIC par la loi »),
et chaque erreur fabrique de faux écarts au programme. Un modèle d'une autre famille relit chaque
engagement porteur d'une position et répond « conforme », « autre » (avec la bonne position) ou
« aucune ». Le fichier `data/programme/<source>.json` garde la trace : position d'origine, avis, raison.
Un engagement jugé « aucune » perd sa position et ne compte plus.

    python -m src.scripts.verifier_programme [--sources rn-2022 rn-2024-legislatives] [--essai]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys

os.environ.setdefault("SCHEDULER_ENABLED", "false")

PROMPT = """Programme : {titre}
Passage (livret « {livret} », page {page}) :
« {verbatim} »

Question : {question}
Échelle : {echelle}
Position attribuée au programme : {position} ({label})"""

SYSTEM = (
    "Tu vérifies la lecture d'un programme politique. On te donne un passage, une question fermée avec son "
    "échelle de réponses, et la position qu'un premier lecteur a attribuée au programme. Le passage engage-t-il "
    "le parti sur CETTE question, et sur cette position ?\n\n"
    "- « conforme » : oui.\n"
    "- « autre » : le passage répond bien à la question, mais par une autre position de l'échelle ; donne son code.\n"
    "- « aucune » : le passage ne répond pas à cette question (autre sujet, simple constat, propos d'un tiers).\n\n"
    "Lis la mesure telle qu'elle est écrite, sans y ajouter ce que le parti a pu dire ailleurs.\n"
    'Réponds par un JSON : {"avis": "conforme|autre|aucune", "position": null, "raison": "une phrase"}'
)


async def verifier(sources: list[str] | None, essai: bool) -> int:
    from src.config import get_settings
    from src.services.analysis.claim_llm import get_claim_llm
    from src.services.analysis.ecarts import Avis
    from src.services.analysis.enjeux import PAR_SLUG
    from src.services.analysis.programme import DATA_DIR

    llm, juge2 = get_claim_llm(), get_settings().juge2_model
    total = {"conforme": 0, "autre": 0, "aucune": 0, "echecs": 0}
    for path in sorted(DATA_DIR.glob("*.json")):
        doc = json.loads(path.read_text(encoding="utf-8"))
        if sources and doc["source"] not in sources:
            continue
        a_voir = [e for e in doc["engagements"] if e.get("position") and "avis" not in e and e["enjeu"] in PAR_SLUG]
        print(f"{doc['source']} : {len(a_voir)} engagements à relire", flush=True)
        if essai:
            continue
        for e in a_voir:
            enjeu = PAR_SLUG[e["enjeu"]]
            cran = enjeu.cran(e["position"])
            prompt = PROMPT.format(titre=doc["titre"], livret=e["livret"], page=e.get("page") or "?",
                                   verbatim=e["verbatim"], question=enjeu.question,
                                   echelle=" ; ".join(f"{c.code} = {c.label}" for c in enjeu.echelle),
                                   position=e["position"], label=cran.label if cran else "?")
            try:
                a = await llm.ask_json(tier=2, system=SYSTEM, prompt=prompt, schema=Avis,
                                       task="programme_avis", max_tokens=600, raisonnement="low", model=juge2)
            except Exception as exc:  # noqa: BLE001
                total["echecs"] += 1
                print(f"   échec : {str(exc)[:120]}", flush=True)
                continue
            avis = a.avis if a.avis in ("conforme", "autre", "aucune") else "conforme"
            e["avis"], e["avis_raison"], e["position_lue"] = avis, a.raison[:300], e["position"]
            if avis == "aucune":
                e["position"] = None
            elif avis == "autre" and a.position and enjeu.cran(a.position):
                e["position"] = a.position
            total[avis] += 1
            if avis != "conforme":
                print(f"   {avis} : {e['enjeu']} {e['position_lue']} -> {e['position']} | {e['verbatim'][:90]}", flush=True)
        path.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"Bilan : {total}", flush=True)
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--sources", nargs="*")
    p.add_argument("--essai", action="store_true")
    a = p.parse_args()
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    return asyncio.run(verifier(a.sources, a.essai))


if __name__ == "__main__":
    raise SystemExit(main())
