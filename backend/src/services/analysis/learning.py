"""Boucle d'apprentissage — le système s'améliore à l'usage, pas à l'intervention.

Chaque décision d'un relecteur est un exemple étiqueté. Jusqu'ici on les jetait :
le statut passait à confirmé/écarté et rien n'en était tiré. Le juge répétait
donc indéfiniment les mêmes erreurs, et sa précision n'était pas mesurée.

Trois usages de ces décisions, du moins au plus utile :

1. **Mesure** — précision du juge (confirmés / décidés), globale, par type et
   par motif de rejet. Sans elle, « ça marche mieux » est une impression.
2. **Diagnostic** — chaque motif de rejet désigne une cause DIFFÉRENTE, donc un
   correctif différent : « objets_differents » accuse le regroupement en sujets,
   « pas_contradictoire » accuse le juge, « attribution_fausse » accuse
   l'extraction. La répartition dit où travailler.
3. **Correction** — les décisions deviennent des exemples few-shot dans le
   prompt du juge. C'est de l'apprentissage réel, sans réentraînement : cheap,
   immédiat, et surtout AUDITABLE — on peut lire ce que le système a appris.

Amorçage. Cette boucle n'ouvre qu'à partir de cinq décisions, et un observatoire
qui démarre en a zéro : elle ne pouvait donc jamais partir. La doctrine écrite à
la main (`doctrine.py`) fournit le plancher — règles éditoriales et cas d'école
tranchés — et les décisions de la rédaction viennent l'affiner par-dessus.

Choix assumé : on privilégie les exemples ÉCARTÉS. Un juge qui sur-détecte coûte
la crédibilité du produit ; lui montrer ses faux positifs corrige plus que lui
montrer ses réussites.
"""

from __future__ import annotations

from collections import Counter

import structlog
from sqlalchemy import func, select

from src.database import get_session_factory
from src.models.claim import Claim
from src.models.contradiction import REJECTION_REASONS, Contradiction

logger = structlog.get_logger(__name__)

# Bornes du few-shot : un prompt qui enfle coûte à chaque appel et noie la
# consigne. Quelques exemples bien choisis valent mieux qu'un catalogue.
MAX_EXAMPLES = 6
MAX_REJECTED = 4  # majorité d'écartés : c'est la sur-détection qui fait mal


async def judge_precision() -> dict:
    """Précision du juge d'après les décisions humaines.

    Ne compte que ce qui a été TRANCHÉ : une file en attente n'est pas un
    résultat, et compter les `pending` comme des succès serait se mentir.
    """
    factory = get_session_factory()
    async with factory() as db:
        rows = list(
            (
                await db.execute(
                    select(Contradiction.detection_method, Contradiction.status,
                           Contradiction.type, Contradiction.rejection_reason)
                    .where(Contradiction.status.in_(("confirmed", "rejected")))
                )
            ).all()
        )
        pending = await db.scalar(
            select(func.count()).select_from(Contradiction)
            .where(Contradiction.status == "pending")
        ) or 0

    by_method: dict[str, Counter] = {}
    by_type: dict[int, Counter] = {}
    reasons: Counter = Counter()
    for method, status, ctype, reason in rows:
        by_method.setdefault(method or "deterministe", Counter())[status] += 1
        by_type.setdefault(ctype, Counter())[status] += 1
        if status == "rejected" and reason:
            reasons[reason] += 1

    def rate(c: Counter) -> float | None:
        n = c["confirmed"] + c["rejected"]
        return round(c["confirmed"] / n, 3) if n else None

    return {
        "decided": len(rows),
        "pending": pending,
        "precision": rate(Counter(s for _, s, _, _ in rows)),
        "by_method": {m: {"decided": sum(c.values()), "precision": rate(c)}
                      for m, c in by_method.items()},
        "by_type": {t: {"decided": sum(c.values()), "precision": rate(c)}
                    for t, c in by_type.items()},
        # Le diagnostic : chaque motif accuse un étage différent du pipeline.
        "rejection_reasons": [
            {"reason": r, "n": n, "means": REJECTION_REASONS.get(r, "")}
            for r, n in reasons.most_common()
        ],
        "enough_to_learn": len(rows) >= 5,
    }


async def few_shot_examples(*, limit: int = MAX_EXAMPLES) -> list[dict]:
    """Exemples tirés des décisions humaines, à injecter dans le prompt du juge.

    Les plus RÉCENTS d'abord : la doctrine éditoriale se précise avec le temps,
    et une décision de la semaine dernière reflète mieux ce qu'on veut
    aujourd'hui qu'une décision d'il y a six mois.
    """
    factory = get_session_factory()
    async with factory() as db:
        rows = list(
            (
                await db.execute(
                    select(Contradiction)
                    .where(Contradiction.status.in_(("confirmed", "rejected")))
                    .order_by(Contradiction.validated_at.desc().nullslast())
                    .limit(limit * 3)
                )
            ).scalars().all()
        )

        out: list[dict] = []
        n_rejected = 0
        for c in rows:
            if len(out) >= limit:
                break
            rejected = c.status == "rejected"
            if rejected and n_rejected >= MAX_REJECTED:
                continue
            a = await db.get(Claim, c.claim_a_id)
            b = await db.get(Claim, c.claim_b_id)
            if a is None or b is None:
                continue
            out.append({
                "a": (a.canonical or a.verbatim or "")[:220],
                "b": (b.canonical or b.verbatim or "")[:220],
                "verdict": "contradiction" if not rejected else "pas une contradiction",
                "reason": (REJECTION_REASONS.get(c.rejection_reason, "")
                           if rejected else (c.rationale or "")[:200]),
            })
            n_rejected += rejected
    return out


def render_examples(examples: list[dict]) -> str:
    """Bloc de texte à ajouter à la consigne du juge. Vide si rien à montrer."""
    if not examples:
        return ""
    lines = [
        "\nDÉCISIONS DÉJÀ PRISES PAR LA RÉDACTION SUR CE CORPUS — "
        "aligne-toi sur elles :",
    ]
    for i, e in enumerate(examples, 1):
        lines.append(
            f"{i}. A : « {e['a']} »\n"
            f"   B : « {e['b']} »\n"
            f"   → {e['verdict']}" + (f" ({e['reason']})" if e["reason"] else "")
        )
    return "\n".join(lines)


async def judge_system_prompt(base: str) -> str:
    """Consigne du juge : doctrine posée, puis décisions de la rédaction.

    L'ordre compte. La DOCTRINE vient toujours — un observatoire qui démarre a
    zéro décision humaine, donc zéro apprentissage, et personne ne relit cent
    rapprochements d'un juge qui n'a rien appris. Le système attendait un
    amorçage qui ne pouvait pas venir ; il part désormais instruit.

    Les DÉCISIONS de la rédaction viennent après, et priment : elles sont plus
    bas dans la consigne, donc plus proches de la tâche, et elles portent sur ce
    corpus-ci. La doctrine est un plancher, pas un plafond.
    """
    from src.services.analysis.doctrine import doctrine_block

    prompt = f"{base}\n{doctrine_block()}"
    stats = await judge_precision()
    if not stats["enough_to_learn"]:
        return prompt
    block = render_examples(await few_shot_examples())
    if block:
        logger.info("learning.prompt_augmented", decided=stats["decided"])
    return prompt + block
