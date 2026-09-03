"""Le registre des engagements — ce à quoi ils se sont engagés, et depuis quand.

Méthode. Le Polimètre de l'Université Laval suit les promesses d'un
gouvernement selon une règle qui décide de tout : ne sont retenus que les
engagements VÉRIFIABLES, c'est-à-dire ceux dont on peut dire, en observant le
monde, s'ils ont été tenus. « Nous serons plus fermes sur l'immigration » n'est
pas un engagement au sens du Polimètre — aucune observation ne le tranche.
« Nous supprimerons l'aide médicale d'État » en est un. Cinq verdicts existent
(réalisée, partiellement réalisée, en cours, en attente, rompue), et tout
changement de verdict exige une source.

Ce que ça donne ici, et sa limite, dite franchement. Le corpus suit une
opposition qui n'a jamais gouverné : aucun de ces engagements ne peut être
« réalisé » ou « rompu » aujourd'hui, ils sont tous « en attente ». Publier des
verdicts n'aurait donc aucun sens pour l'instant. Ce qui a du sens dès
maintenant, c'est le REGISTRE : consigner, daté et sourcé, ce à quoi chacun
s'engage, pour pouvoir le confronter à ce qu'il dira ensuite — et, le moment
venu, à ce qui aura été fait. Les cinq verdicts existent en base, prêts ; la
machine n'en pose aucun.

Détection en deux questions, comme le codage CAP et pour la même raison — une
question unique laisse le modèle confondre l'engagement avec l'opinion :

  Q1  le locuteur engage-t-il SA propre action future ? (tier 1, court)
  Q2  qu'observerait-on pour dire que c'est tenu ?      (tier 2, structuré)

Q2 est le filtre de vérifiabilité : un engagement dont le modèle ne sait pas
dire ce qu'on observerait n'entre pas au registre.

Pré-filtre gratuit : seuls les propos NORMATIFS et PRÉDICTIFS sont examinés.
Un constat factuel n'engage personne, et c'est les trois quarts du corpus
qu'on n'a pas à soumettre.
"""

from __future__ import annotations

import structlog
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select

from src.database import get_session_factory
from src.models.claim import Claim
from src.services.analysis.claim_llm import get_claim_llm
from src.services.analysis.declaration_extractor import verbatim_in_source
from src.services.analysis.llm_usage import BudgetExceeded, ProviderRefused

logger = structlog.get_logger(__name__)

PROTOCOLE = "engagement-2q-v1"

# Les cinq verdicts du Polimètre. Aucun n'est posé par la machine : le passage
# de « en attente » à autre chose est une décision humaine, sourcée.
EN_ATTENTE = "en attente"
VERDICTS = (EN_ATTENTE, "en cours", "partiellement réalisée", "réalisée", "rompue")

# Un constat n'engage pas. Restreindre le lot ne coûte rien et divise par
# quatre le nombre d'appels.
TYPES_CANDIDATS = ("normatif", "predictif")

Q1_SYSTEM = """Tu détermines si une déclaration politique contient un ENGAGEMENT
du locuteur — c'est-à-dire s'il annonce ce que LUI, son parti ou son
gouvernement FERA.

Réponds OUI seulement si le locuteur engage sa propre action future :
  « nous supprimerons », « je rétablirai », « notre premier acte sera de… ».

Réponds NON dans tous les autres cas, et notamment :
  · une opinion ou un jugement de valeur (« c'est une catastrophe »),
  · une injonction adressée à d'autres (« le gouvernement doit démissionner »,
    « il faut que l'Europe agisse ») — exiger n'est pas s'engager,
  · une prédiction sur ce qui va arriver sans que le locuteur en soit l'auteur,
  · un constat, une critique, une attaque.

La distinction tient en une question : après cette phrase, est-ce que quelqu'un
pourra dire que LE LOCUTEUR a tenu ou non parole ?

Réponds par un seul mot : OUI ou NON."""

Q2_SYSTEM = """Tu établis ce qu'il faudrait OBSERVER pour dire qu'un engagement
politique a été tenu.

C'est la règle qui décide : un engagement ne se suit que s'il est vérifiable.
« Nous serons plus fermes » n'est vérifiable par aucune observation ; « nous
supprimerons l'aide médicale d'État » l'est par une seule.

Rends :
  · `verbatim` : le fragment EXACT du TEXTE ORIGINAL qui porte l'engagement,
    recopié mot pour mot. Jamais un fragment de la reformulation, jamais une
    phrase que tu composes ;
  · `mesure` : en une phrase, ce qu'on devrait constater pour dire que c'est
    tenu (« l'AME est supprimée par une loi ») ;
  · `verifiable` : false si aucune observation ne permettrait de trancher.

Devant une formule d'intention sans objet observable, réponds verifiable=false.
Mieux vaut un registre court et sûr qu'un registre long et invérifiable."""


class EngagementLu(BaseModel):
    verbatim: str = Field(description="Fragment EXACT de la déclaration.")
    mesure: str = Field(description="Ce qu'on devrait observer pour dire que c'est tenu.")
    verifiable: bool = Field(description="False si aucune observation ne tranche.")


def _todo():
    """Les propos susceptibles d'engager, pas encore examinés."""
    return (
        Claim.claim_type.in_(TYPES_CANDIDATS),
        or_(Claim.pledge_version.is_(None),
            ~Claim.pledge_version.startswith(PROTOCOLE)),
    )


async def detect_pledges(*, limit: int = 400) -> dict:
    """Examine les propos candidats et consigne ceux qui engagent."""
    llm = get_claim_llm()
    if not llm.available():
        return {"engagements": 0, "skipped": "LLM indisponible (clé tier-2 absente)"}

    factory = get_session_factory()
    async with factory() as db:
        lot = list((await db.execute(
            select(Claim).where(*_todo())
            .order_by(Claim.published_at.desc().nullslast()).limit(limit)
        )).scalars().all())

    signature = f"{PROTOCOLE}/{llm._s.claim_tier2_model}"
    retenus = examines = non_verifiables = hors_source = echecs = 0
    budget_hit = False

    for c in lot:
        brut = (c.verbatim or "").strip()
        if not brut:
            continue
        try:
            lu = await llm.read_pledge(verbatim=brut, canonical=c.canonical)
        except BudgetExceeded as exc:
            logger.warning("engagements.budget_exceeded", detail=str(exc))
            budget_hit = True
            break
        except ProviderRefused:
            raise
        except Exception as exc:  # noqa: BLE001
            # Rien de marqué : la déclaration repassera. La marquer écrirait
            # « examiné, aucun engagement » sur un propos jamais lu.
            logger.warning("engagements.claim_failed", claim_id=c.id,
                           error=str(exc)[:120])
            echecs += 1
            continue
        examines += 1

        garde = None
        if lu is not None and lu.verifiable:
            # Le fragment doit venir du texte, comme partout ailleurs : un
            # engagement reformulé par le modèle est un engagement qu'on prête.
            if verbatim_in_source(lu.verbatim, brut):
                garde = lu
            else:
                hors_source += 1
        elif lu is not None:
            non_verifiables += 1

        async with factory() as db:
            obj = await db.get(Claim, c.id)
            if obj is None:
                continue
            obj.pledge_version = signature
            if garde is not None:
                obj.pledge_measure = garde.mesure.strip()[:400]
                # Aucun verdict posé par la machine : l'engagement entre au
                # registre, il n'y est pas jugé.
                obj.pledge_status = EN_ATTENTE
                retenus += 1
            await db.commit()

    async with factory() as db:
        reste = await db.scalar(
            select(func.count()).select_from(Claim).where(*_todo())) or 0

    stats = {"engagements": retenus, "examines": examines,
             "non_verifiables": non_verifiables, "hors_source": hors_source,
             "echecs": echecs,
             "remaining": reste, "budget_exceeded": budget_hit}
    logger.info("engagements.done", **stats)
    return stats
