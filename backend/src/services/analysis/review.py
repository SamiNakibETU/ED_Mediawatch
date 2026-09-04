"""La revue périodique d'un sujet — ce qui s'est dit, par qui, et ce qui diverge.

Le produit ne s'arrête pas à une base bien tenue : il doit proposer un angle de
lecture. Cette étape écrit, par sujet et par période, la revue de ce qui s'y est
dit — mais sous une contrainte qui la sépare d'un résumé génératif ordinaire.

La contrainte : chaque paragraphe porte les identifiants des déclarations qu'il
rapporte, et un paragraphe qui n'en cite aucune, ou qui en cite une qu'on ne lui
a pas donnée, est retiré avant enregistrement. C'est la même règle que pour le
verbatim (`verbatim_in_source`) et l'attribution (`attributed_speaker`) : le
modèle propose, la source dispose. Sans elle, la revue serait l'endroit exact où
toutes les précautions prises en amont — vérification du verbatim, attribution
littérale, parti daté — seraient annulées par une phrase inventée.

Une revue ne se régénère pas. Elle décrit un état du corpus à une date ; la
réécrire plus tard avec ce qui est arrivé depuis produirait un texte qui n'a
jamais été vrai au moment qu'il prétend décrire. La clé unique en base l'impose,
et l'étape saute ce qui existe déjà — ce qui la rend aussi reprenable.

Elle reste un brouillon jusqu'à relecture humaine, comme les contradictions.

CE QUI MANQUAIT. La revue ne voyait que la semaine en cours. Elle pouvait donc
décrire, jamais dire CE QUI A CHANGÉ — c'est-à-dire précisément ce que le
produit promet. Un observatoire qui republie chaque semaine un état des lieux
sans mémoire produit des bulletins interchangeables ; « tenir le compte de ce
qui se dit » suppose de savoir ce qui se disait avant.

L'antériorité est donc fournie à part, bornée aux déclarations les mieux classées
du même sujet avant la période. Deux garde-fous : le rédacteur peut la citer
(sinon il ne pourrait pas montrer le déplacement), mais une revue qui ne citerait
QUE du passé n'est pas la revue de la semaine et n'est pas enregistrée. Et la
règle 4 tient toujours — rapprocher deux propos n'est pas conclure à la
contradiction, ce que seul un relecteur fait.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import structlog
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from src.database import get_session_factory
from src.models.claim import Claim
from src.models.review import Review
from src.models.subject import Subject
from src.services.analysis.claim_llm import get_claim_llm
from src.services.analysis.llm_usage import BudgetExceeded

logger = structlog.get_logger(__name__)

CADENCE = "hebdomadaire"
# Assez de matière pour qu'une revue ait un objet, sans quoi elle paraphrase une
# déclaration unique et se lit comme un communiqué.
MIN_CLAIMS = 3
MIN_SPEAKERS = 2
# L'antériorité donnée au rédacteur : les mieux classées, pas les plus récentes
# — c'est le classement éditorial qui dit ce qui faisait référence sur ce sujet.
# Bornée, parce qu'un contexte de deux cents propos noie la semaine à décrire.
ANTERIEURS_MAX = 12


class Paragraphe(BaseModel):
    texte: str = Field(description="Deux à quatre phrases, en français, au factuel.")
    claim_ids: list[int] = Field(
        default_factory=list,
        description="Identifiants des déclarations rapportées dans ce paragraphe.",
    )


class RevueEcrite(BaseModel):
    titre: str = Field(description="Titre court, descriptif, sans jugement.")
    paragraphes: list[Paragraphe] = Field(default_factory=list)


_SYSTEM = """Tu rédiges la revue hebdomadaire d'un observatoire du discours
politique. Un lecteur doit savoir, en la lisant, QUI a dit QUOI sur ce sujet
cette semaine, et où les positions divergent.

Règles, dans l'ordre :

1. Tu n'écris que ce que les déclarations fournies établissent. Aucun contexte
   extérieur, aucune date, aucun chiffre, aucun événement qui ne s'y trouve pas.
2. Chaque paragraphe cite dans `claim_ids` les déclarations qu'il rapporte. Un
   paragraphe sans identifiant sera supprimé.
3. Tu nommes les locuteurs. « Le parti estime que » n'est pas une observation,
   c'est une généralisation : ce sont des personnes qui parlent.
4. Quand deux locuteurs disent des choses incompatibles, tu le montres en les
   rapportant côte à côte, sans conclure à la contradiction : établir une
   contradiction est le travail d'un relecteur, pas le tien.
5. Ton neutre et descriptif. Ni dénonciation, ni reprise à ton compte des
   formules employées. Tu rapportes un propos, tu ne l'endosses pas.
6. Si des déclarations antérieures te sont fournies, ton dernier paragraphe dit
   ce qui a changé depuis : un locuteur qui revient sur le sujet dans d'autres
   termes, une position nouvelle, une voix qui se tait. Tu cites les deux côtés,
   l'ancien et le nouveau. Si rien n'a bougé, tu l'écris — « les positions sont
   inchangées depuis » est une information, pas un aveu d'échec. Tu ne conclus
   jamais qu'un locuteur s'est contredit : tu rapportes les deux propos.

Trois à cinq paragraphes. Pas d'introduction ni de conclusion générale."""


def periode_hebdo(quand: datetime) -> tuple[str, datetime, datetime]:
    """Clé ISO de la semaine et ses bornes. « 2026-W36 », lundi → lundi."""
    an, sem, _ = quand.isocalendar()
    debut = datetime.fromisocalendar(an, sem, 1).replace(tzinfo=timezone.utc)
    return f"{an}-W{sem:02d}", debut, debut + timedelta(days=7)


def ground(revue: RevueEcrite, autorises: set[int]) -> tuple[list[dict], list[int]]:
    """Ne garde que ce qui est adossé aux déclarations effectivement fournies.

    Deux rejets, pour deux fautes distinctes. Un paragraphe sans citation est
    une affirmation dont on ne peut pas remonter la source — inutilisable dans
    un observatoire, quelle que soit sa justesse. Un paragraphe qui cite un
    identifiant absent du lot est plus grave : le modèle a fabriqué une
    référence, et rien ne dit que le reste de la phrase soit mieux fondé.
    """
    gardes: list[dict] = []
    cites: list[int] = []
    for p in revue.paragraphes:
        ids = [i for i in (p.claim_ids or [])]
        if not ids or not set(ids) <= autorises:
            logger.info("revue.paragraphe_rejete",
                        raison="sans source" if not ids else "source inventée",
                        ids=ids[:5])
            continue
        gardes.append({"texte": p.texte.strip(), "claim_ids": ids})
        cites.extend(ids)
    return gardes, sorted(set(cites))


def _contexte(claims: list[Claim]) -> str:
    lignes = []
    for c in claims:
        quand = c.published_at.strftime("%d/%m") if c.published_at else "sans date"
        qui = c.speaker_name or "locuteur non établi"
        parti = f" ({c.party})" if c.party else ""
        lignes.append(f"[{c.id}] {quand} — {qui}{parti} : "
                      f"« {(c.canonical or c.verbatim or '').strip()[:400]} »")
    return "\n".join(lignes)


async def build_reviews(*, limit: int = 6, semaines: int = 1) -> dict:
    """Écrit les revues manquantes des dernières semaines closes."""
    llm = get_claim_llm()
    if not llm.available():
        return {"ecrites": 0, "skipped": "LLM indisponible (clé tier-2 absente)"}

    factory = get_session_factory()
    maintenant = datetime.now(timezone.utc)
    ecrites = sautees = vides = 0
    budget_hit = False

    for recul in range(1, semaines + 1):
        # Semaines CLOSES seulement : une revue de la semaine en cours serait
        # démentie par les déclarations du lendemain, et elle ne se réécrit pas.
        period, debut, fin = periode_hebdo(maintenant - timedelta(days=7 * recul))

        async with factory() as db:
            actifs = (await db.execute(
                select(Claim.subject_id,
                       func.count(Claim.id),
                       func.count(func.distinct(Claim.speaker_name)))
                .where(Claim.subject_id.isnot(None),
                       Claim.published_at >= debut, Claim.published_at < fin)
                .group_by(Claim.subject_id)
            )).all()
            assez = [sid for sid, n, voix in actifs
                     if n >= MIN_CLAIMS and voix >= MIN_SPEAKERS]
            # Seulement les sujets NOMMÉS. Un sujet resté en « auto » porte les
            # mots-clés de son regroupement — « adherents affilies cfdt » — et
            # une revue titrée là-dessus se lit comme une sortie de machine, ce
            # qu'elle est. L'étape dépend du nommage ; encore faut-il qu'il ait
            # abouti pour ce sujet-là.
            candidats = list((await db.execute(
                select(Subject.id).where(Subject.id.in_(assez), Subject.status != "auto",
                                         Subject.status != "incoherent")
                .order_by(Subject.relevance.desc().nullslast())
                .limit(limit)
            )).scalars().all()) if assez else []
            if not candidats:
                continue
            deja = set((await db.execute(
                select(Review.subject_id).where(
                    Review.cadence == CADENCE, Review.period == period,
                    Review.subject_id.in_(candidats))
            )).scalars().all())

        for sid in candidats:
            if sid in deja:
                sautees += 1
                continue
            async with factory() as db:
                sujet = await db.get(Subject, sid)
                claims = list((await db.execute(
                    select(Claim).where(Claim.subject_id == sid,
                                        Claim.published_at >= debut,
                                        Claim.published_at < fin)
                    .order_by(Claim.published_at)
                )).scalars().all())
                # Ce qui se disait avant : la mémoire sans laquelle une revue
                # hebdomadaire n'est qu'un bulletin de plus.
                anterieurs = list((await db.execute(
                    select(Claim).where(Claim.subject_id == sid,
                                        Claim.published_at < debut)
                    .order_by(Claim.relevance.desc().nullslast(),
                              Claim.published_at.desc())
                    .limit(ANTERIEURS_MAX)
                )).scalars().all())
            if sujet is None or not claims:
                continue
            anterieurs.sort(key=lambda c: c.published_at or debut)

            prompt = (f"Sujet : {sujet.label or 'sans nom'}\n"
                      f"Semaine : {period}\n\n"
                      f"Déclarations de la semaine :\n{_contexte(claims)}"
                      + (f"\n\nCe qui avait été dit sur ce sujet AVANT cette "
                         f"semaine :\n{_contexte(anterieurs)}" if anterieurs else ""))
            try:
                ecrite = await llm.write_review(prompt=prompt, system=_SYSTEM)
            except BudgetExceeded as exc:
                logger.warning("revue.budget_exceeded", detail=str(exc))
                budget_hit = True
                break
            if ecrite is None:
                continue

            de_la_semaine = {c.id for c in claims}
            paragraphes, cites = ground(
                ecrite, de_la_semaine | {c.id for c in anterieurs})
            # Une revue qui ne cite que l'antériorité décrit le passé, pas la
            # semaine : elle porterait un titre de période qu'elle ne couvre pas.
            if paragraphes and not de_la_semaine.intersection(cites):
                logger.info("revue.hors_periode", subject_id=sid, period=period)
                paragraphes = []
            if not paragraphes:
                # Tout a été rejeté : on n'enregistre pas une revue vide, et on
                # ne marque rien — la semaine repassera.
                vides += 1
                continue

            async with factory() as db:
                db.add(Review(
                    cadence=CADENCE, period=period, subject_id=sid,
                    title=ecrite.titre.strip()[:240],
                    body=paragraphes, claim_ids=cites,
                    status="brouillon", model=llm._s.claim_tier2_model,
                    generated_at=datetime.now(timezone.utc),
                ))
                await db.commit()
            ecrites += 1
        if budget_hit:
            break

    stats = {"ecrites": ecrites, "deja_ecrites": sautees, "rejetees": vides,
             "budget_exceeded": budget_hit}
    logger.info("revue.done", **stats)
    return stats
