"""Nommage des sujets par le LLM — donner un titre lisible à un groupe de propos.

Le regroupement produit des sujets cohérents mais nommés par un sac d'entités
(« augmenter expression fiscale impots »). Illisible pour un militant ou un
journaliste, alors que le groupe porte bien sur « la hausse des impôts ».

Un appel par sujet, sur un échantillon borné de ses déclarations. Le modèle ne
fait que NOMMER : il ne résume pas, ne juge pas, n'ajoute rien. Coût mesuré :
~0,0002 $ par sujet.

Idempotent : un sujet déjà nommé (status « labelled » ou curé à la main) n'est
pas renommé — sinon un libellé validé par un humain serait écrasé au run suivant.
"""

from __future__ import annotations

from typing import Literal

import structlog
from pydantic import BaseModel, Field
from sqlalchemy import select

from src.database import get_session_factory
from src.models.claim import Claim
from src.models.subject import Subject
from src.services.analysis.claim_llm import get_claim_llm
from src.services.analysis.llm_usage import BudgetExceeded

logger = structlog.get_logger(__name__)

LABEL_PROMPT_VERSION = "subject-label-v2"  # v2 : une personne n'est pas un objet de débat


class SubjectLabel(BaseModel):
    """Nom d'un sujet, tel qu'un journaliste l'écrirait dans un sommaire."""

    label: str = Field(
        description="Groupe nominal de 2 à 6 mots nommant l'OBJET commun aux "
        "déclarations : « la hausse des impôts », « l'aide militaire à "
        "l'Ukraine », « la reconnaissance de l'État de Palestine ». Pas de "
        "verbe conjugué, pas de nom de locuteur, pas de jugement."
    )
    coherent: bool = Field(
        description="Faux si les déclarations ne portent PAS sur un objet commun "
        "— dans ce cas le regroupement est à revoir, ne force pas un nom."
    )


_SYSTEM = (
    "Tu nommes des groupes de déclarations politiques. On te donne plusieurs "
    "propos rassemblés automatiquement ; tu produis le nom de l'OBJET dont ils "
    "parlent tous.\n"
    "Règles :\n"
    "1. Un groupe nominal court, comme un titre de rubrique : « la hausse des "
    "impôts », « l'aide militaire à l'Ukraine ».\n"
    "2. L'objet, jamais le locuteur ni sa position.\n"
    "3. Un NOM DE PERSONNE n'est pas un objet de débat. « Jordan Bardella » ne "
    "dit pas de quoi on parle ; nomme ce qui se dit DE lui — « la candidature "
    "de Jordan Bardella », « le bilan de Jordan Bardella au Parlement "
    "européen ». Même chose pour un parti ou une institution : « le RN » n'est "
    "pas un sujet, « la dédiabolisation du RN » en est un.\n"
    "4. Le même objet reçoit toujours le même nom, à la lettre près : c'est ce "
    "qui permet de rapprocher deux propos tenus à deux ans d'écart.\n"
    "5. Si les propos ne partagent pas d'objet commun, coherent=false et ne "
    "force pas un nom. Un groupe mal formé signalé vaut mieux qu'un titre "
    "inventé qui masque le défaut."
)


async def label_subjects(*, limit: int = 60, min_speakers: int = 1) -> dict:
    """Nomme les sujets non encore nommés, les plus fournis d'abord."""
    llm = get_claim_llm()
    if not llm.available():
        return {"labelled": 0, "skipped": "LLM indisponible"}

    factory = get_session_factory()
    async with factory() as db:
        subs = list(
            (
                await db.execute(
                    select(Subject)
                    .where(Subject.status == "auto", Subject.n_speakers >= min_speakers)
                    .order_by(Subject.n_claims.desc())
                    .limit(limit)
                )
            ).scalars().all()
        )

    labelled = incoherent = 0
    budget_hit = False
    for s in subs:
        async with factory() as db:
            claims = list(
                (
                    await db.execute(
                        select(Claim.canonical, Claim.verbatim, Claim.stance_target)
                        .where(Claim.subject_id == s.id)
                        .limit(12)
                    )
                ).all()
            )
        if not claims:
            continue
        extraits = "\n".join(f"- {(c or v or '')[:180]}" for c, v, _ in claims)
        # Les objets déclarés à l'extraction, quand ils existent : le modèle a
        # déjà nommé l'objet propos par propos, autant s'en servir plutôt que de
        # le lui faire redécouvrir depuis les extraits.
        cibles = sorted({t.strip() for _, _, t in claims if t and t.strip()})[:8]
        prompt = (
            f"Déclarations regroupées :\n{extraits}\n"
            + (f"\nObjets déclarés à l'extraction : {', '.join(cibles)}\n" if cibles else "")
            + (f"\nEntités récurrentes : {', '.join((s.entities or [])[:10])}\n"
               if s.entities else "")
            + "\nTâche : nomme l'objet commun à ces propos."
        )
        try:
            res = await llm.label_subject(prompt, _SYSTEM)
        except BudgetExceeded as exc:
            logger.warning("subject_label.budget_exceeded", detail=str(exc))
            budget_hit = True
            break
        if res is None:
            continue

        async with factory() as db:
            obj = await db.get(Subject, s.id)
            if obj is None:
                continue
            if res.coherent:
                obj.label = res.label[:300]
                obj.status = "labelled"
                labelled += 1
            else:
                # Le groupe ne tient pas : on le signale plutôt que de lui
                # coller un nom qui masquerait le défaut de regroupement.
                obj.status = "incoherent"
                obj.note = "Le modèle ne trouve pas d'objet commun — regroupement à revoir."
                incoherent += 1
            await db.commit()

    stats = {"labelled": labelled, "incoherent": incoherent,
             "examined": len(subs), "budget_exceeded": budget_hit,
             "prompt_version": LABEL_PROMPT_VERSION}
    logger.info("subjects.labelled", **stats)
    return stats
