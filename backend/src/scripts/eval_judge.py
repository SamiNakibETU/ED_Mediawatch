"""Évalue le juge sur les cas d'école — pour que « ça marche mieux » soit mesuré.

    python -m src.scripts.eval_judge            # règles seules (le vrai test)
    python -m src.scripts.eval_judge --avec-cas # règles + cas d'école

Pourquoi deux modes. Les cas d'école servent d'exemples DANS la consigne du
juge. Les lui redonner à l'évaluation reviendrait à corriger une copie avec le
corrigé posé dessus : on mesurerait sa capacité à recopier, pas à juger.

Le mode par défaut retire donc les cas de la consigne et ne garde que les
RÈGLES. Ce qu'on mesure alors est la seule chose qui compte : est-ce que les
règles écrites suffisent à trancher des situations qu'on n'a pas montrées.

Le second mode existe pour la comparaison — l'écart entre les deux dit ce que
les exemples apportent en plus des règles. Si l'écart est nul, les exemples ne
servent à rien et coûtent des jetons ; s'il est énorme, les règles sont mal
écrites et c'est là qu'il faut travailler.

Coût : 14 appels, de l'ordre de 0,01 $. À lancer après toute modification de la
consigne ou de la doctrine.
"""

import asyncio
import sys

from src.services.analysis.claim_llm import get_claim_llm
from src.services.analysis.contradiction_judge import _JUDGE_SYSTEM
from src.services.analysis.doctrine import DOCTRINE_VERSION, GOLD, RULES, doctrine_block


def _prompt(case: dict) -> str:
    """Reproduit exactement le prompt de production (`_pair_prompt`).

    Un banc d'essai qui simplifie le prompt ne mesure plus le système : la
    première version omettait locuteur et date, et le juge répondait « les
    locuteurs ne sont pas identifiés » — une réponse juste à une question qu'on
    ne lui posait pas en production.
    """
    return (
        f"Sujet de rapprochement : {case['subject']}\n\n"
        f"[A] {case['who_a']}, {case['when_a']} :\n« {case['a']} »\n\n"
        f"[B] {case['who_b']}, {case['when_b']} :\n« {case['b']} »\n\n"
        "Tâche : ces deux déclarations se contredisent-elles ? Donne le verdict, "
        "une explication neutre, et ta confiance."
    )


async def main() -> None:
    avec_cas = "--avec-cas" in sys.argv
    llm = get_claim_llm()
    if not llm.available():
        print("LLM indisponible : renseigne OPENROUTER_API_KEY.")
        return

    system = _JUDGE_SYSTEM + "\n" + (doctrine_block() if avec_cas else RULES)
    mode = "règles + cas d'école" if avec_cas else "règles seules"
    print(f"\nÉvaluation du juge — {DOCTRINE_VERSION}, {mode}")
    print(f"{len(GOLD)} cas\n")

    justes = 0
    ratés: list[tuple[dict, str, str]] = []
    for i, case in enumerate(GOLD, 1):
        res = await llm.judge_contradiction(_prompt(case), system)
        rendu = getattr(res, "verdict", None) if res else None
        ok = rendu == case["verdict"]
        justes += ok
        if not ok:
            ratés.append((case, rendu or "aucune réponse", getattr(res, "explanation", "") or ""))
        print(f"  {'ok  ' if ok else 'RATÉ'} {i:2d}. attendu {case['verdict']:18s} "
              f"rendu {rendu or '—'}")

    print(f"\nJustes : {justes}/{len(GOLD)}  ({round(100 * justes / len(GOLD))} %)")

    if ratés:
        # Le détail des ratés vaut plus que le score : il désigne la règle à
        # réécrire. Un score seul dit qu'on a un problème, pas lequel.
        print("\nCe qui n'est pas passé :")
        for case, rendu, pourquoi in ratés:
            print(f"\n  A : « {case['a']} »")
            print(f"  B : « {case['b']} »")
            print(f"  attendu : {case['verdict']} — {case['why']}")
            print(f"  rendu   : {rendu} — {pourquoi[:160]}")
    print()


if __name__ == "__main__":
    asyncio.run(main())
