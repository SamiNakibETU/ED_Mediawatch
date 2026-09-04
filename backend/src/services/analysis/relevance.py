"""Ce qui compte — la priorisation que la chaîne n'avait pas.

Le défaut d'origine du produit tient en une phrase : on a pris l'exhaustivité
pour la valeur. Tout est collecté, extrait, regroupé, nommé, puis mis en vitrine
— 8 420 déclarations sous neuf angles, sans qu'aucun ne dise ce qui compte. Une
rédaction n'imprime pas tout ce qu'elle entend. Et la méthode adoptée pour la
vérification (CheckThat!) place explicitement une étape de PRIORISATION entre la
détection et le rapprochement ; on l'avait sautée. Les agents nommaient les
sujets par ordre de taille, le juge comparait au hasard des blocs, la revue
prenait les six premiers venus.

Les signaux sont en base depuis le début, sur chaque post, gratuits : likes,
retweets, citations, abonnés du locuteur, reprise par la presse, présence dans
une contradiction, engagement pris. Personne ne les lisait.

LA RÈGLE QUI DÉCIDE : l'audience se lit PAR LOCUTEUR, jamais en brut. Mesuré sur
le corpus : Damien Rieu fait 17 000 en médiane, Marine Le Pen 2 100, Éric Ciotti
72. Les likes bruts classeraient un militant devant la cheffe du parti. Ce qui
compte, c'est l'inhabituel pour CE locuteur — un tweet de Ciotti à 800 est un
signal, un tweet de Rieu à 17 000 n'en est pas un. La portée institutionnelle
(abonnés) entre à part, bornée, pour que la cheffe du parti ne disparaisse pas
derrière ses propres routines.

Chaque déclaration reçoit un score ET la liste en clair de ce qui l'a fait
monter — « relayée 2 400 fois, cinq fois sa moyenne · reprise dans la presse ».
Un score sans son pourquoi serait une boîte noire de plus ; ici la page peut le
dire au lecteur, et le lecteur peut ne pas être d'accord.

Le score se recalcule entièrement à chaque passe. Il est dérivé, pas accumulé :
la leçon des compteurs de sujets vaut ici aussi.
"""

from __future__ import annotations

import math
import statistics
from datetime import datetime, timezone

import structlog
from sqlalchemy import func, select

from src.database import get_session_factory
from src.models.claim import Claim
from src.models.contradiction import Contradiction
from src.models.personality import Personality
from src.models.post import Post
from src.models.subject import Subject
from src.services.analysis.cap import CAP_VERSION

logger = structlog.get_logger(__name__)

# Poids des signaux. Ils se lisent comme des priorités éditoriales, et c'est
# ce qu'ils sont : une contradiction vaut plus qu'une reprise presse, qui vaut
# plus qu'une audience inhabituelle. Aucun n'écrase les autres à lui seul.
POIDS = {
    "audience": 1.0,        # z-score borné à [0, 3]
    "portee": 0.8,          # [0, 1] — log des abonnés
    "presse": 1.2,          # 0 / 1
    # Une contradiction est le matériau même de l'observatoire : elle doit
    # passer devant N'IMPORTE QUEL signal d'audience seul, y compris le plus
    # viral (z borné à 3). D'où 3,5, et non 2 comme au premier jet, où un
    # tweet simplement très relayé faisait jeu égal avec un revirement.
    "contradiction": 3.5,   # 0 / 1 (détectée) / 1.5 (confirmée)
    "engagement": 1.0,      # 0 / 1
    "recence": 0.6,         # [0, 1] — décroissance sur un mois
}
AUDIENCE_MAX_Z = 3.0
# En dessous de trois cents relais pondérés, « inhabituel pour lui » ne veut
# rien dire : un locuteur à 72 de médiane fait « 5× sa moyenne » avec un tweet
# à 370, qui n'a été vu par personne. Le z-score mesure l'écart, pas l'ampleur ;
# il lui faut un plancher d'ampleur.
AUDIENCE_PLANCHER = 300
# Un propos codé « hors politique publique » — remerciement, agenda, salut —
# n'entre pas en une, quelle que soit son audience. « Accueilli mon ami à la
# mairie » peut faire vingt fois la moyenne d'un compte ; ce n'est pas ce qu'un
# observatoire du discours politique met en tête. Le codage le sait. On ne
# pénalise pas ce qui n'est PAS ENCORE codé : l'inconnu n'est pas le hors-sujet.
HORS_SUJET_FACTEUR = 0.3
# Un propos que la presse RAPPORTE — sans guillemets, donc dans les mots du
# journaliste — reste du matériau : un observatoire suit aussi ce qui est écrit
# sur ces gens. Mais il ne vaut pas la parole tenue. Mesuré le 04/09/2026 :
# 3 100 des 3 294 propos de presse étaient dans ce cas, et ils occupaient toute
# la une, guillemets compris. Rétrogradés, pas exclus — la distinction est
# affichée, le lecteur tranche.
RAPPORTE_FACTEUR = 0.5
RECENCE_JOURS = 30.0
# Un locuteur dont on a moins de six posts n'a pas de « moyenne » : on ne peut
# pas dire qu'un tweet est inhabituel pour lui, on retombe sur la portée seule.
MIN_POSTS_POUR_NORMALISER = 6


def audience_brute(likes, retweets, quotes) -> float:
    """Une seule grandeur pour trois compteurs. Le retweet vaut deux likes (il
    relaie), la citation trois (elle prend position). En log : la distribution
    est en loi de puissance, et sans le log un seul tweet viral écraserait tout
    le reste du calcul."""
    return math.log1p((likes or 0) + 2 * (retweets or 0) + 3 * (quotes or 0))


def audience_normalisee(brute: float, mediane: float, ecart: float) -> float:
    """Combien cette audience est inhabituelle POUR CE LOCUTEUR, en écarts
    types robustes (MAD), bornée. Zéro ou moins = routine."""
    if ecart <= 0:
        return 0.0
    return max(0.0, min(AUDIENCE_MAX_Z, (brute - mediane) / ecart))


def portee(followers: int | None) -> float:
    """Poids institutionnel, en [0, 1]. Trois millions d'abonnés → ~0,9 ;
    dix mille → ~0,55 ; mille → ~0,4. Borné pour ne jamais faire le score seul."""
    return min(1.0, math.log10((followers or 0) + 1) / 7.0)


def recence(quand: datetime | None, maintenant: datetime) -> float:
    if quand is None:
        return 0.0
    if quand.tzinfo is None:
        quand = quand.replace(tzinfo=timezone.utc)
    jours = max(0.0, (maintenant - quand).total_seconds() / 86400)
    return math.exp(-jours / RECENCE_JOURS)


def score(signaux: dict[str, float], *, hors_sujet: bool = False,
          rapporte: bool = False) -> float:
    brut = sum(POIDS[k] * signaux.get(k, 0.0) for k in POIDS)
    if hors_sujet:
        brut *= HORS_SUJET_FACTEUR
    if rapporte:
        brut *= RAPPORTE_FACTEUR
    return round(brut, 3)


def pourquoi(signaux: dict[str, float], *, brut_audience: int, facteur: float,
             confirmee: bool) -> list[str]:
    """Les raisons en clair, dans l'ordre où elles pèsent. C'est ce que la page
    affiche à côté d'une déclaration ; sans ça le classement serait une boîte
    noire, et un lecteur ne peut pas contester une boîte noire."""
    raisons: list[str] = []
    if signaux.get("contradiction"):
        raisons.append("contredit un autre propos" + (" — confirmé" if confirmee else ""))
    if signaux.get("presse"):
        raisons.append("reprise dans la presse")
    if signaux.get("engagement"):
        raisons.append("engagement pris")
    if signaux.get("audience", 0) >= 1.0:
        n = f"{brut_audience:,}".replace(",", " ")
        raisons.append(f"relayée {n} fois, {facteur:.0f}× sa moyenne"
                       if facteur >= 2 else f"relayée {n} fois")
    return raisons


async def compute_relevance() -> dict:
    """Recalcule le score de toutes les déclarations, puis celui des sujets."""
    factory = get_session_factory()
    maintenant = datetime.now(timezone.utc)

    async with factory() as db:
        # 1. La distribution d'audience de chaque locuteur — la médiane et
        #    l'écart robuste de SES posts. C'est ce qui rend les locuteurs
        #    comparables entre eux.
        rows = (await db.execute(
            select(Post.personality_id, Post.likes, Post.retweets, Post.quotes)
            .where(Post.likes.isnot(None))
        )).all()
        par_locuteur: dict[int, list[float]] = {}
        for pid, l, r, q in rows:
            par_locuteur.setdefault(pid, []).append(audience_brute(l, r, q))
        stats: dict[int, tuple[float, float]] = {}
        for pid, vals in par_locuteur.items():
            if len(vals) < MIN_POSTS_POUR_NORMALISER:
                continue
            med = statistics.median(vals)
            mad = statistics.median(abs(v - med) for v in vals) or 0.0
            stats[pid] = (med, 1.4826 * mad)   # MAD → écart type robuste

        abonnes = dict((await db.execute(
            select(Personality.id, Personality.followers_count))).all())

        # 2. Les déclarations prises dans une contradiction, et lesquelles sont
        #    confirmées par un relecteur.
        en_contradiction: dict[int, bool] = {}
        for a, b, statut in (await db.execute(
            select(Contradiction.claim_a_id, Contradiction.claim_b_id,
                   Contradiction.status)
            .where(Contradiction.status != "rejected")
        )).all():
            for cid in (a, b):
                en_contradiction[cid] = en_contradiction.get(cid, False) or statut == "confirmed"

        # 3. Le score, déclaration par déclaration.
        claims = (await db.execute(
            select(Claim.id, Claim.personality_id, Claim.post_id, Claim.article_id,
                   Claim.published_at, Claim.pledge_status,
                   Claim.cap_version, Claim.cap_major, Claim.quote_style,
                   Post.likes, Post.retweets, Post.quotes)
            .outerjoin(Post, Post.id == Claim.post_id)
        )).all()

        maj = 0
        for (cid, pid, post_id, article_id, quand, pledge, capv, capm, style,
             l, r, q) in claims:
            # Codé, et codé « aucun objet d'action publique ».
            hors_sujet = bool(capv and capv.startswith(CAP_VERSION)) and capm is None
            signaux = {
                "portee": portee(abonnes.get(pid)),
                "presse": 1.0 if article_id else 0.0,
                "engagement": 1.0 if pledge else 0.0,
                "recence": recence(quand, maintenant),
            }
            confirmee = en_contradiction.get(cid)
            if cid in en_contradiction:
                signaux["contradiction"] = 1.5 if confirmee else 1.0
            brut, facteur = 0, 0.0
            if post_id and pid in stats:
                med, ecart = stats[pid]
                a = audience_brute(l, r, q)
                brut = (l or 0) + 2 * (r or 0) + 3 * (q or 0)
                if brut >= AUDIENCE_PLANCHER:
                    signaux["audience"] = audience_normalisee(a, med, ecart)
                    facteur = math.expm1(a) / max(1.0, math.expm1(med))
            obj = await db.get(Claim, cid)
            if obj is None:
                continue
            obj.relevance = score(signaux, hors_sujet=hors_sujet,
                                  rapporte=style == "rapporte")
            obj.relevance_why = pourquoi(signaux, brut_audience=brut,
                                         facteur=facteur, confirmee=bool(confirmee))
            maj += 1
        await db.commit()

        # 4. Le sujet vaut ce que vaut sa déclaration la plus forte, plus un
        #    peu pour chaque voix : un sujet où deux personnes se répondent
        #    compte plus qu'un monologue de même intensité.
        par_sujet = dict((await db.execute(
            select(Claim.subject_id, func.max(Claim.relevance))
            .where(Claim.subject_id.isnot(None))
            .group_by(Claim.subject_id)
        )).all())
        sujets = 0
        for s in (await db.execute(select(Subject))).scalars().all():
            s.relevance = round((par_sujet.get(s.id) or 0.0)
                                + 0.3 * max(0, (s.n_speakers or 1) - 1), 3)
            sujets += 1
        await db.commit()

    out = {"declarations": maj, "sujets": sujets,
           "locuteurs_normalises": len(stats)}
    logger.info("relevance.done", **out)
    return out
