"""Mesure la fiabilité du codage thématique contre un jeu annoté à la main.

    python -m src.scripts.eval_cap
    python -m src.scripts.eval_cap --limit 20        # passe rapide

Ce qui est mesuré, et pourquoi pas un taux d'accord. Un pourcentage brut ne
prouve rien quand une catégorie domine : deux codeurs qui rangent 80 % des
propos dans la même catégorie majoritaire obtiennent 80 % d'accord et un alpha
de −0,06, c'est-à-dire moins bien que le hasard. L'alpha de Krippendorff corrige
de l'accord attendu par chance ; c'est la mesure retenue par la littérature qui
évalue l'annotation par modèle.

Seuils établis de l'analyse de contenu :

    α ≥ 0,80    fiable
    0,67 – 0,79 provisoire, utilisable en signalant la réserve
    α < 0,67    non fiable, revoir la consigne avant tout usage

Repère utile : le CAP mesure 95 % d'accord entre codeurs humains formés au
niveau des topiques majeurs. Un modèle qui atteindrait 100 % contre un seul
annotateur serait suspect, pas rassurant — il aurait appris cet annotateur.

Limite de ce jeu. Cinquante déclarations, annotées par UNE personne. C'est un
point de départ mesurable, pas une référence établie : les seuils supposent
plusieurs codeurs indépendants et une adjudication des désaccords. Le jeu est à
étendre et à faire annoter par un second codeur ; d'ici là, l'alpha se lit comme
un indicateur de régression, pas comme une validation.
"""

import asyncio
import json
import pathlib
import sys
from collections import Counter

from src.services.analysis.cap import coder_signature, label
from src.services.analysis.claim_llm import get_claim_llm
from src.services.analysis.reliability import krippendorff_alpha, verdict

GOLD = pathlib.Path(__file__).resolve().parents[1] / "data" / "cap_gold.jsonl"


def _arg(name: str, default: int) -> int:
    if name in sys.argv:
        try:
            return int(sys.argv[sys.argv.index(name) + 1])
        except (IndexError, ValueError):
            pass
    return default


def load_gold() -> list[dict]:
    if not GOLD.exists():
        return []
    return [json.loads(line) for line in GOLD.read_text(encoding="utf-8").splitlines() if line.strip()]


async def main() -> None:
    gold = load_gold()[: _arg("--limit", 999)]
    if not gold:
        print(f"\nAucun jeu annoté à {GOLD}.\n")
        return

    llm = get_claim_llm()
    if not llm.available():
        print("LLM indisponible : renseigne OPENROUTER_API_KEY.")
        return

    print(f"\nÉvaluation du codage thématique — {len(gold)} déclarations annotées")
    print(f"Codeur : {coder_signature(llm._s.claim_tier1_model)}\n")

    unites: list[list] = []
    ecarts: Counter = Counter()
    justes = 0
    # `None` est une DÉCISION (« hors politique publique »), pas une absence de
    # réponse : on la code explicitement, sinon l'alpha écarterait précisément
    # les cas où les deux codeurs s'accordent le plus.
    HORS = 0

    for i, cas in enumerate(gold, 1):
        rendu = await llm.code_cap(cas["text"])
        humain = cas["code"]
        unites.append([humain if humain is not None else HORS,
                       rendu if rendu is not None else HORS])
        ok = rendu == humain
        justes += ok
        if not ok:
            ecarts[(label(humain), label(rendu))] += 1
        print(f"  {'ok  ' if ok else 'ÉCART'} {i:2d}. humain {label(humain):<38s} "
              f"modèle {label(rendu)}")

    alpha = krippendorff_alpha(unites)
    taux = round(100 * justes / len(gold))
    print(f"\nAccord brut        : {justes}/{len(gold)}  ({taux} %)")
    print(f"Alpha de Krippendorff : {alpha:.3f}" if alpha is not None
          else "Alpha : non mesurable")
    print(f"Verdict            : {verdict(alpha)}")

    if ecarts:
        # Le détail vaut plus que le score : il désigne la règle à réécrire.
        print("\nOù les deux divergent :")
        for (h, m), k in ecarts.most_common(10):
            print(f"  {k:2d} ×  humain « {h} »  →  modèle « {m} »")

    hors_humain = sum(1 for c in gold if c["code"] is None)
    print(f"\nHors politique publique, selon l'annotation humaine : "
          f"{hors_humain}/{len(gold)} ({round(100 * hors_humain / len(gold))} %)\n")


if __name__ == "__main__":
    asyncio.run(main())
