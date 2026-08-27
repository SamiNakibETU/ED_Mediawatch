"""Juge sémantique de contradictions (A4) — au-delà des chiffres et des stances.

La détection déterministe (`contradiction_detector`) ne retient une paire que si
les valeurs chiffrées divergent, ou si les `stance_polarity` sont explicitement
opposées. Or ce champ est rempli au L0 sur une déclaration ISOLÉE : deux prises
de position contraires formulées autrement (« ce dispositif doit être maintenu »
vs « il faut y mettre fin ») passent au travers. C'est précisément le revirement
qu'un observatoire électoral doit attraper.

Méthode en deux temps (arXiv:2505.19191, « Misleading through Inconsistency ») :

  1. **Appariement candidat — gratuit.** Blocking par `referent_key` (déjà posé
     par `enrich_claims`), puis filtre par cosinus sur les embeddings existants :
     on ne garde que les paires assez PROCHES pour parler du même objet, mais pas
     au point d'être des quasi-doublons (répétition du même propos ≠ revirement).
  2. **Verdict LLM — budgété.** Une paire = un appel structuré. Le juge qualifie
     le type d'inconsistance plutôt que de répondre oui/non : un changement de
     position assumé et daté n'est pas une contradiction cachée.

Toute arête créée reste `pending` : le juge propose, l'humain dispose. Le coût
est borné par `max_pairs` et par le garde-budget (BudgetExceeded → arrêt propre,
reprise au run suivant).
"""

from __future__ import annotations

from typing import Literal

import structlog
from pydantic import BaseModel, Field
from sqlalchemy import select

from src.database import get_session_factory
from src.models.claim import Claim
from src.models.contradiction import Contradiction
from src.models.referentiel import Referent
from src.services.analysis.claim_llm import get_claim_llm
from src.services.analysis.contradiction_detector import _classify, _existing_pairs
from src.services.analysis.embeddings import cosine
from src.services.analysis.llm_usage import BudgetExceeded

logger = structlog.get_logger(__name__)

JUDGE_PROMPT_VERSION = "judge-v1"

# Fenêtre de similarité des candidats, CALIBRÉE sur le corpus réel (26/08/2026,
# 212 102 paires locuteur×thème, embeddings MiniLM local 384d) :
#   médiane 0.21, p90 0.44 — la masse des paires ne parle pas du même objet ;
#   ~0.75 : même cible, propos génériques (« Macron a échoué » / « incapable ») ;
#   ~0.82 : même objet, positions distinctes — LA zone utile ;
#   ~0.90 : la même phrase reformulée par l'extracteur, pas un revirement.
# Un seuil bas (0.55) noyait le juge sous 5 412 paires sans objet commun :
# 100 examinées, 0 contradiction, 83 « compatible ». Les valeurs ci-dessous sont
# liées au modèle d'embeddings — à recalibrer si l'on en change.
SIM_MIN = 0.78
SIM_MAX = 0.93

# Écart minimal entre deux propos du MÊME locuteur pour parler de revirement.
# Mesuré : le juge a qualifié « contradiction » deux déclarations extraites du
# même post, le même jour — le L0 avait segmenté une phrase unique en deux
# lectures qui se recouvrent. Se dédire suppose du temps ; en deçà, c'est du
# bruit d'extraction, pas un changement de position.
MIN_GAP_DAYS = 7


class ContradictionVerdict(BaseModel):
    """Verdict structuré sur une paire de déclarations du même locuteur/parti."""

    verdict: Literal[
        "contradiction",      # les deux ne peuvent pas être tenues ensemble
        "evolution_assumee",  # changement de position explicitement reconnu
        "compatible",         # tension apparente mais conciliable (périmètres)
        "hors_sujet",         # les deux propos ne portent pas sur le même objet
    ]
    explanation: str = Field(
        description="Une à deux phrases neutres expliquant l'opposition ou son "
        "absence, en s'appuyant UNIQUEMENT sur les deux déclarations fournies."
    )
    confidence: float = Field(ge=0.0, le=1.0)


_JUDGE_SYSTEM = (
    "Tu es un analyste politique rigoureux. On te donne DEUX déclarations réelles "
    "(datées, attribuées) portant potentiellement sur le même sujet. Tu détermines "
    "si elles se contredisent.\n"
    "Règles ABSOLUES :\n"
    "1. Juge UNIQUEMENT sur le contenu fourni. N'invente aucun contexte, ne "
    "suppose pas ce que la personne pense vraiment.\n"
    "2. Une contradiction = les deux positions ne peuvent pas être tenues "
    "ensemble sur le MÊME objet, au MÊME périmètre. Des chiffres différents sur "
    "des périmètres différents (national vs régional, annuel vs total) ne sont "
    "PAS une contradiction -> 'compatible'.\n"
    "3. Si l'une des deux reconnaît explicitement un changement de position "
    "(« j'ai changé d'avis », « nous avons fait évoluer notre position ») -> "
    "'evolution_assumee', pas 'contradiction'.\n"
    "4. Si les deux ne portent pas sur le même objet -> 'hors_sujet'.\n"
    "5. Dans le doute, choisis le verdict le MOINS accusatoire. Une fausse "
    "contradiction publiée détruit la crédibilité de l'analyse ; un faux négatif "
    "coûte seulement une occasion manquée.\n"
    "6. `explanation` reste neutre et factuelle, sans qualificatif moral."
)


def _pair_prompt(a: Claim, b: Claim, referent_label: str) -> str:
    def side(c: Claim, tag: str) -> str:
        who = c.speaker_name or c.party or "source presse"
        when = c.published_at.date().isoformat() if c.published_at else "date inconnue"
        text = c.canonical or c.verbatim
        return f"[{tag}] {who}, {when} :\n« {text} »"

    return (
        f"Sujet de rapprochement : {referent_label}\n\n"
        f"{side(a, 'A')}\n\n{side(b, 'B')}\n\n"
        "Tâche : ces deux déclarations se contredisent-elles ? Donne le verdict, "
        "une explication neutre, et ta confiance."
    )


def _candidate_pairs(
    claims: list[Claim], seen: set[tuple[int, int]]
) -> list[tuple[Claim, Claim, float]]:
    """Paires plausibles d'un même bloc : proches sans être des doublons."""
    out: list[tuple[Claim, Claim, float]] = []
    for i in range(len(claims)):
        for j in range(i + 1, len(claims)):
            a, b = claims[i], claims[j]
            if tuple(sorted((a.id, b.id))) in seen:
                continue
            # Un locuteur inconnu des deux côtés ne permet aucune imputation.
            if not (a.speaker_name or a.party) or not (b.speaker_name or b.party):
                continue
            # Même source = même propos : deux segmentations du L0 ne se
            # contredisent pas, elles se recouvrent.
            if (a.post_id and a.post_id == b.post_id) or (a.article_id and a.article_id == b.article_id):
                continue
            # Même locuteur : exiger un écart de temps réel (cf. MIN_GAP_DAYS).
            same_speaker = a.speaker_name and a.speaker_name == b.speaker_name
            if same_speaker and a.published_at and b.published_at:
                if abs((a.published_at - b.published_at).days) < MIN_GAP_DAYS:
                    continue
            sim = cosine(a.embedding, b.embedding)
            if SIM_MIN <= sim <= SIM_MAX:
                out.append((a, b, sim))
    # Classement par POTENTIEL DE REVIREMENT, pas par similarité.
    #
    # Trier par similarité décroissante fait examiner en premier les paires qui
    # se ressemblent le plus — c'est-à-dire celles qui répètent la même position.
    # Mesuré : 120 paires triées ainsi → 98 « compatible », 0 contradiction.
    # Ce qu'on cherche est l'inverse : un propos thématiquement proche mais
    # ÉLOIGNÉ DANS LE TEMPS, du même locuteur. C'est la définition du drift.
    return sorted(out, key=_drift_potential, reverse=True)


def _drift_potential(pair: tuple[Claim, Claim, float]) -> tuple[int, float, float]:
    """Clé de tri : (même locuteur, écart en jours, similarité).

    Le même locuteur d'abord — se dédire soi-même est le plus accablant et le
    plus défendable. Puis l'écart temporel : deux ans séparent une évolution
    d'une reformulation. La similarité ne départage plus qu'à égalité.
    """
    a, b, sim = pair
    same_speaker = int(bool(a.speaker_name and a.speaker_name == b.speaker_name))
    gap = 0.0
    if a.published_at and b.published_at:
        gap = abs((a.published_at - b.published_at).days)
    return (same_speaker, gap, sim)


async def run_semantic_judging(max_pairs: int = 60) -> dict:
    """Juge les paires candidates non encore examinées. Idempotent, budgété."""
    llm = get_claim_llm()
    if not llm.available():
        return {"judged": 0, "skipped": "LLM indisponible (clé tier-2 absente)"}

    factory = get_session_factory()
    async with factory() as db:
        seen = await _existing_pairs(db)
        labels = dict((await db.execute(select(Referent.key, Referent.label))).all())
        claims = list(
            (
                await db.execute(
                    select(Claim).where(
                        Claim.embedding.isnot(None),
                        Claim.qty_value.is_(None),  # le chiffré est déjà traité
                        # Bloc = référent si rattaché, sinon (locuteur, thème) :
                        # sur corpus réel, ~90 % des déclarations n'atteignent
                        # aucun des 28 référents (grille fine, discours large).
                        # Sans ce second blocking, le juge ne verrait presque rien.
                        (Claim.subject_id.isnot(None))
                        | (Claim.referent_key.isnot(None))
                        | (Claim.speaker_name.isnot(None) & Claim.theme.isnot(None)),
                    )
                )
            ).scalars().all()
        )

    # Bloc = SUJET. C'est la correction d'architecture du 28/08 : bloquer par
    # thème (15 rayons) faisait comparer « les ministres macronistes ruinent la
    # France » avec « la situation sera irréversible » — même rayon, objets
    # différents. Un sujet (« la hausse des impôts ») garantit que les deux
    # propos portent sur la MÊME chose ; c'est la condition pour qu'une
    # contradiction ait un sens. Repli sur l'ancien découpage tant que les
    # sujets ne sont pas construits.
    blocks: dict[str, list[Claim]] = {}
    for c in claims:
        if c.subject_id:
            key = f"subject:{c.subject_id}"
        elif c.referent_key:
            key = c.referent_key
        else:
            key = f"speaker:{c.speaker_name}|theme:{c.theme}"
        blocks.setdefault(key, []).append(c)

    candidates: list[tuple[Claim, Claim, float]] = []
    for block in blocks.values():
        candidates.extend(_candidate_pairs(block, seen))
    candidates.sort(key=lambda t: t[2], reverse=True)
    truncated = max(0, len(candidates) - max_pairs)
    candidates = candidates[:max_pairs]

    verdicts: dict[str, int] = {}
    created = 0
    budget_hit = False
    for a, b, sim in candidates:
        label = labels.get(a.referent_key) or a.referent_key or f"thème « {a.theme} »"
        try:
            res = await llm.judge_contradiction(_pair_prompt(a, b, label))
        except BudgetExceeded as exc:
            logger.warning("judge.budget_exceeded", detail=str(exc))
            budget_hit = True
            break
        if res is None:
            verdicts["echec"] = verdicts.get("echec", 0) + 1
            continue
        verdicts[res.verdict] = verdicts.get(res.verdict, 0) + 1
        if res.verdict != "contradiction":
            continue
        ca, cb = sorted((a.id, b.id))
        async with factory() as db:
            db.add(Contradiction(
                claim_a_id=ca, claim_b_id=cb, referent_key=a.referent_key,
                type=_classify(a, b),
                # Score = confiance du juge, pondérée par la proximité du bloc.
                score=round(min(res.confidence, 1.0) * min(sim + 0.15, 1.0), 3),
                rationale=res.explanation[:1000],
                status="pending",
                detection_method="llm_judge",
                judge_version=JUDGE_PROMPT_VERSION,
            ))
            await db.commit()
        created += 1

    stats = {
        "pairs_examined": len(candidates),
        "contradictions_new": created,
        "verdicts": verdicts,
        "pairs_truncated": truncated,
        "budget_exceeded": budget_hit,
        "judge_version": JUDGE_PROMPT_VERSION,
    }
    logger.info("judge.done", **stats)
    return stats
