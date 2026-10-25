"""Le registre des déclarations : chaque tweet lu une fois, en trois étages.

1. **Prétri, en code, gratuit.** Un retweet simple porte les mots d'un autre ;
   un tweet de quelques mots ne porte pas de position ; un tweet en anglais
   n'est pas l'objet. Ils sont marqués lus sans appel.
2. **Filtre, au tier 1, par lots de ~25 tweets.** Une seule question : y a-t-il
   au moins une déclaration de l'auteur ? Le filtre est réglé pour laisser
   passer dans le doute : une erreur ici coûte un appel de plus à l'étage 3,
   un oubli coûterait la déclaration.
3. **Extraction, au tier 2, par lots de ~8 tweets.** Chaque déclaration rangée
   dans le référentiel (enjeu, position), ou gardée hors liste avec son objet.

Le coût vient surtout de la consigne, pas du tweet : le référentiel pèse
environ 2 500 tokens, un tweet 70. D'où les lots, et d'où une consigne qui ne
change jamais et passe en tête de chaque appel, là où le fournisseur la met en
cache. Mesuré sur un appel par tweet, la consigne représentait 95 % de la
facture.

Trois règles de fidélité tiennent l'ensemble. Le modèle ne voit jamais le nom
de l'auteur. Le verbatim rendu doit se retrouver dans le tweet, sinon la
déclaration n'est pas écrite. Un appel raté n'écrit rien et ne marque rien :
le tweet repassera.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
import structlog
from pydantic import BaseModel, Field
from sqlalchemy import or_, select

from src.database import get_session_factory
from src.models.declaration import Declaration
from src.models.post import Post
from src.services.analysis.declaration_extractor import verbatim_in_source
from src.services.analysis.enjeux import (
    ENJEUX_VERSION, HORS_LISTE, PAR_SLUG, referentiel_pour_prompt,
)
from src.services.analysis.llm_usage import BudgetExceeded, ProviderRefused
from src.utils import sha256

logger = structlog.get_logger(__name__)

# Version de la lecture : consignes et référentiel. Une version nouvelle relit
# tout, l'ancienne marque reste visible sur chaque tweet.
CONSIGNES_VERSION = "registre-2"
VERSION = f"{CONSIGNES_VERSION}/{ENJEUX_VERSION}"

LOT_FILTRE = 25
LOT_EXTRACTION = 8
# Réflexion des modèles qui raisonnent : coupée au filtre (une question de tri
# n'en a pas besoin, et elle multipliait la facture de sortie par 30).
RAISONNEMENT_FILTRE = "off"
# Courte à l'extraction : sur la référence de 100 tweets, elle divise par trois
# les rangements forcés (1 à 2 contre 3 à 6), pour 50 % de coût en plus.
RAISONNEMENT_EXTRACTION = "low"
MIN_MOTS = 5


# ── Étage 1 : prétri ────────────────────────────────────────────────────

def _mots(texte: str) -> int:
    t = re.sub(r"https?://\S+", " ", texte or "")
    t = re.sub(r"[@#]\w+", " ", t)
    return len(re.findall(r"[^\W\d_]{2,}", t))


def pretri(post: Post) -> str | None:
    """La raison d'écarter un tweet sans le lire, ou None s'il part au filtre."""
    if post.is_retweet or post.post_type == "retweet":
        return "retweet"
    if _mots(post.content) < MIN_MOTS:
        return "trop_court"
    lang = (post.lang or "fr").lower()
    # Les codes en « q » (qme, qht…) et « und » sont des textes sans langue
    # sûre — un emoji, un hashtag : le compte de mots a déjà jugé.
    if lang not in ("fr", "und") and not lang.startswith("q"):
        return "langue"
    return None


# ── Étage 2 : filtre ────────────────────────────────────────────────────

FILTRE_SYSTEM = (
    "Tu tries des tweets publiés par des responsables politiques français. Pour chaque tweet, "
    "tu dis s'il contient au moins une DÉCLARATION de son auteur.\n\n"
    "Une déclaration est une phrase où l'auteur dit lui-même ce qu'il veut, propose, promet, "
    "refuse ou soutient sur une politique publique ou une question de société, ou avance un "
    "chiffre comme un fait. Exemples : « nous rétablirons la retraite à 60 ans », « il faut "
    "sortir du commandement intégré de l'OTAN », « je voterai contre ce texte », « l'immigration "
    "coûte X milliards par an ».\n\n"
    "N'en sont PAS : l'agenda, les invitations, les remerciements, les annonces de passage dans "
    "un média, les condoléances, le soutien à un candidat ou à un parti, les appels à voter "
    "ou à adhérer, les attaques ou moqueries qui ne disent pas ce que l'auteur "
    "veut à la place, le récit de l'actualité, les propos d'autres personnes que l'auteur "
    "rapporte ou cite.\n\n"
    "Comptent aussi : approuver ou regretter le vote d'autres élus sur une mesure, dire "
    "ce que l'Europe ou le gouvernement « doit » faire.\n\n"
    "Dans le doute, retiens le tweet : une lecture plus attentive suivra.\n\n"
    'Réponds par un JSON : {"retenus": [les numéros des tweets retenus]}. Une liste vide si aucun.'
)


class Filtre(BaseModel):
    retenus: list[int] = Field(default_factory=list)


def _bloc(numero: int, post: Post) -> str:
    texte = (post.content or "").strip()[:1500]
    out = f"[{numero}] {texte}"
    if post.quoted_content:
        out += f"\n    (tweet cité, écrit par quelqu'un d'autre : {post.quoted_content.strip()[:300]})"
    return out


def prompt_filtre(posts: list[Post]) -> str:
    return "\n\n".join(_bloc(i + 1, p) for i, p in enumerate(posts))


# ── Étage 3 : extraction ────────────────────────────────────────────────

EXTRACTION_SYSTEM = (
    "Tu lis des tweets publiés par des responsables politiques français et tu en tires les "
    "DÉCLARATIONS de leur auteur, pour un registre qui compare leurs positions dans le temps. "
    "Tu ne sais pas qui a écrit chaque tweet, et tu ne dois pas chercher à le deviner : seul "
    "compte ce que le texte dit.\n\n"
    "# Ce qu'est une déclaration\n"
    "Une phrase où l'auteur dit lui-même ce qu'il veut, propose, promet, refuse ou soutient, ou "
    "avance un chiffre comme un fait. Une position rapportée, critiquée ou prêtée à quelqu'un "
    "d'autre n'est pas la sienne. Une attaque n'est une déclaration que si elle dit ce que "
    "l'auteur veut à la place. Soutenir un candidat ou un parti, appeler à voter, vanter son "
    "camp n'est pas une déclaration : seule compte une position sur une politique publique ou "
    "une question de société. Le tweet cité, écrit par quelqu'un d'autre, sert seulement à "
    "comprendre.\n\n"
    "# Comment la ranger\n"
    "1. Si la déclaration répond à l'une des questions du référentiel ci-dessous, donne le "
    "code de l'enjeu et le code de position qui correspond à ce que dit l'auteur. Seulement "
    "les codes écrits dans le référentiel.\n"
    "2. Si elle répond à la question sans qu'aucun cran ne convienne exactement (par exemple "
    "l'auteur refuse 65 ans sans dire quel âge il veut), ou si elle porte sur une autre "
    f"politique, utilise l'enjeu « {HORS_LISTE} », laisse la position à null et écris "
    "l'objet en quelques mots (« refuser la retraite à 65 ans », « baisser les droits de "
    "succession »).\n"
    "3. Ne force jamais un cran. Mieux vaut hors liste qu'un cran deviné.\n"
    "4. Range seulement ce que la phrase dit sur la question elle-même, jamais par voisinage "
    "de thème. Erreurs déjà observées, à ne pas reproduire :\n"
    "   - voter une motion de censure ou s'opposer à un texte en cours d'examen n'est pas "
    "vouloir l'abroger une fois adopté (reforme_2023) : c'est hors liste ;\n"
    "   - un référendum sur un autre sujet (le voile, les institutions) n'est pas le référendum "
    "sur l'immigration ;\n"
    "   - critiquer un pacte ou une politique européenne n'est pas une position sur les "
    "expulsions, ni sur le libre-échange ;\n"
    "   - un texte coupé avant la fin ne se complète pas : ne range que ce qui est écrit.\n"
    "5. Approuver le vote ou la mesure de quelqu'un d'autre (« bravo à ceux qui ont voté pour "
    "supprimer… ») est une déclaration de l'auteur, de modalité « soutient ».\n\n"
    "# Les champs\n"
    "- verbatim : la phrase du tweet qui porte la déclaration, recopiée à l'identique, sans "
    "rien corriger, une phrase au plus. Jamais une phrase du tweet cité.\n"
    "- modalite : « promet » (l'auteur ou son camp s'engage : « nous ferons »), « propose » "
    "(« il faut », « je propose »), « soutient » (il approuve une mesure ou un vote), "
    "« refuse » (il s'oppose à une mesure), « affirme » (il avance un fait chiffré).\n"
    "- certitude : « explicite » si c'est dit, « implicite » si ça se déduit sans hésitation. "
    "Si tu dois deviner, ce n'est pas une déclaration.\n"
    "- valeur et unite : seulement si la phrase contient un chiffre (60 et « ans », 5,5 et "
    "« % », 30 et « milliards d'euros »). Sinon null.\n"
    "- Au plus trois déclarations par tweet, sur des enjeux différents. Un tweet sans "
    "déclaration a une liste vide.\n\n"
    "# Référentiel\n"
    + referentiel_pour_prompt()
    + "\n\n# Réponse\n"
    'Un JSON : {"tweets": [{"numero": 1, "declarations": [{"enjeu": "...", "position": "...", '
    '"objet": null, "modalite": "...", "certitude": "...", "valeur": null, "unite": null, '
    '"verbatim": "..."}]}]}, un objet par tweet, dans l\'ordre.'
)


MODALITES = ("promet", "propose", "soutient", "refuse", "affirme")


class DeclLue(BaseModel):
    # Types larges à la lecture, contrôlés dans `valider` : un champ mal rempli
    # sur une déclaration ne doit pas faire rejeter tout le lot de tweets.
    enjeu: str = ""
    position: str | None = None
    objet: str | None = None
    modalite: str | None = None
    certitude: str | None = None
    valeur: float | str | None = None
    unite: str | None = None
    verbatim: str = ""


class TweetLu(BaseModel):
    numero: int
    declarations: list[DeclLue] = Field(default_factory=list)


class Lot(BaseModel):
    tweets: list[TweetLu] = Field(default_factory=list)


def prompt_extraction(posts: list[Post]) -> str:
    blocs = []
    for i, p in enumerate(posts):
        date = p.published_at.date().isoformat() if p.published_at else "date inconnue"
        blocs.append(_bloc(i + 1, p).replace(f"[{i + 1}] ", f"[{i + 1}] ({date}) ", 1))
    return "\n\n".join(blocs)


def valider(d: DeclLue, texte: str) -> DeclLue | None:
    """La déclaration telle qu'elle s'écrit, ou None si elle ne tient pas."""
    if not d.verbatim or not verbatim_in_source(d.verbatim, texte):
        return None
    try:
        valeur = float(str(d.valeur).replace(",", ".")) if d.valeur not in (None, "") else None
    except ValueError:
        valeur = None
    d = d.model_copy(update={
        "modalite": d.modalite if d.modalite in MODALITES else None,
        "certitude": d.certitude if d.certitude in ("explicite", "implicite") else "explicite",
        "valeur": valeur, "enjeu": (d.enjeu or "").strip()})
    if d.enjeu == HORS_LISTE:
        if not (d.objet or "").strip():
            return None
        return d.model_copy(update={"position": None})
    enjeu = PAR_SLUG.get(d.enjeu)
    if enjeu is None or not enjeu.cran(d.position):
        # Enjeu inventé ou cran hors échelle : on garde la déclaration, mais
        # hors liste, avec ce que le modèle voulait dire comme objet.
        objet = (d.objet or (enjeu.titre if enjeu else d.enjeu) or "").strip()[:200]
        return d.model_copy(update={"enjeu": HORS_LISTE, "position": None, "objet": objet or None})
    return d


# ── Orchestration ───────────────────────────────────────────────────────

async def _marquer(ids: list[int], marque: str) -> None:
    if not ids:
        return
    async with get_session_factory()() as db:
        for p in (await db.execute(select(Post).where(Post.id.in_(ids)))).scalars():
            p.decl_lu = marque
        await db.commit()


async def _ecrire(post: Post, decls: list[DeclLue], lecteur: str) -> int:
    n = 0
    async with get_session_factory()() as db:
        for d in decls:
            cle = sha256(f"{post.id}:{d.enjeu}:{d.verbatim.strip().lower()}")[:64]
            if await db.scalar(select(Declaration.id).where(Declaration.cle == cle)):
                continue
            db.add(Declaration(
                post_id=post.id, personality_id=post.personality_id, published_at=post.published_at,
                enjeu=d.enjeu, position=d.position, objet=(d.objet or None) and d.objet[:200],
                modalite=d.modalite, certitude=d.certitude or "explicite",
                valeur=d.valeur, unite=(d.unite or None) and d.unite[:40],
                verbatim=d.verbatim.strip(), lecteur=lecteur, cle=cle,
            ))
            n += 1
        p = await db.get(Post, post.id)
        if p is not None:
            p.decl_lu = f"{VERSION}:lu"
        await db.commit()
    return n


async def lire(*, limit: int = 1000, plus_recents: bool = False) -> dict:
    """Une passe du registre. Idempotente, reprenable, bornée par le budget."""
    from src.services.analysis.claim_llm import get_claim_llm

    llm = get_claim_llm()
    lecteur = f"{VERSION}/{llm.model_for(1)}+{llm.model_for(2)}"[:160]
    stats = {"ecartes": 0, "filtres": 0, "retenus": 0, "lus": 0, "declarations": 0,
             "rejetees": 0, "echecs": 0, "budget_atteint": False}

    async with get_session_factory()() as db:
        ordre = Post.published_at.desc() if plus_recents else Post.published_at.asc()
        posts = list((await db.execute(
            select(Post).where(or_(Post.decl_lu.is_(None), ~Post.decl_lu.startswith(VERSION)))
            .order_by(ordre.nullslast()).limit(limit)
        )).scalars().all())

    # Étage 1
    a_filtrer: list[Post] = []
    ecartes: dict[str, list[int]] = {}
    for p in posts:
        raison = pretri(p)
        if raison:
            ecartes.setdefault(raison, []).append(p.id)
        else:
            a_filtrer.append(p)
    for raison, ids in ecartes.items():
        await _marquer(ids, f"{VERSION}:ecarte:{raison}")
        stats["ecartes"] += len(ids)

    try:
        # Étage 2
        a_extraire: list[Post] = []
        for i in range(0, len(a_filtrer), LOT_FILTRE):
            lot = a_filtrer[i:i + LOT_FILTRE]
            try:
                f = await llm.ask_json(tier=1, system=FILTRE_SYSTEM, prompt=prompt_filtre(lot),
                                       schema=Filtre, task="registre_filtre", max_tokens=400,
                                       raisonnement=RAISONNEMENT_FILTRE)
            except (BudgetExceeded, ProviderRefused):
                raise
            except Exception as exc:  # noqa: BLE001
                logger.warning("registre.filtre_echec", error=str(exc)[:160])
                stats["echecs"] += len(lot)
                continue
            gardes = {n for n in f.retenus if 1 <= n <= len(lot)}
            a_extraire += [p for n, p in enumerate(lot, 1) if n in gardes]
            await _marquer([p.id for n, p in enumerate(lot, 1) if n not in gardes], f"{VERSION}:sans")
            stats["filtres"] += len(lot)
            stats["retenus"] += len(gardes)

        # Étage 3
        for i in range(0, len(a_extraire), LOT_EXTRACTION):
            lot = a_extraire[i:i + LOT_EXTRACTION]
            try:
                r = await llm.ask_json(tier=2, system=EXTRACTION_SYSTEM, prompt=prompt_extraction(lot),
                                       schema=Lot, task="registre_extraction", max_tokens=4000,
                                       raisonnement=RAISONNEMENT_EXTRACTION)
            except (BudgetExceeded, ProviderRefused):
                raise
            except Exception as exc:  # noqa: BLE001
                logger.warning("registre.extraction_echec", error=str(exc)[:160])
                stats["echecs"] += len(lot)
                continue
            par_numero = {t.numero: t for t in r.tweets}
            for n, post in enumerate(lot, 1):
                t = par_numero.get(n)
                if t is None:
                    # Le modèle a sauté ce tweet : rien n'est écrit, il repassera.
                    stats["echecs"] += 1
                    continue
                bonnes = [v for v in (valider(d, post.content) for d in t.declarations) if v]
                stats["rejetees"] += len(t.declarations) - len(bonnes)
                stats["declarations"] += await _ecrire(post, bonnes, lecteur)
                stats["lus"] += 1
    except BudgetExceeded as exc:
        logger.warning("registre.budget_atteint", detail=str(exc))
        stats["budget_atteint"] = True

    stats["lecteur"] = lecteur
    stats["a"] = datetime.now(timezone.utc).isoformat()
    logger.info("registre.passe", **{k: v for k, v in stats.items() if k != "a"})
    return stats
