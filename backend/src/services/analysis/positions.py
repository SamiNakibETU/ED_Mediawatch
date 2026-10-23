"""Lecture des positions : chaque tweet qui touche un enjeu, rangé sur son échelle.

Trois choix, tous tirés de l'audit du 7 septembre :

* **le passé d'abord** : la file se lit du plus ancien au plus récent. Un
  revirement se voit sur des années, pas sur la dernière semaine ;
* **sans le nom du locuteur** : le modèle classe ce qui est dit. Lui donner le
  nom, c'est l'inviter à répondre ce qu'il sait déjà de la personne ;
* **le verbatim se vérifie** : le fragment rendu par le modèle doit se trouver
  dans le tweet, sinon la position n'est pas écrite.

Les retweets simples sont exclus : ce sont les mots d'un autre. Les citations
restent, avec le tweet cité donné en contexte seulement.
"""

from __future__ import annotations

from typing import Literal

import structlog
from pydantic import BaseModel, Field
from sqlalchemy import and_, exists, func, or_, select

from src.database import get_session_factory
from src.models.personality import Personality
from src.models.position import Position
from src.models.post import Post
from src.services.analysis.declaration_extractor import verbatim_in_source
from src.services.analysis.enjeux import (
    ENJEUX, ENJEUX_VERSION, PAR_SLUG, Enjeu, Point, ecarts,
)
from src.services.analysis.llm_usage import BudgetExceeded, ProviderRefused

logger = structlog.get_logger(__name__)


class PositionLue(BaseModel):
    prend_position: bool = Field(
        description="L'auteur dit-il lui-même ce qu'il pense de la question ?")
    position: str | None = Field(None, description="Le code d'un cran de l'échelle, ou null")
    certitude: Literal["explicite", "implicite"] | None = None
    verbatim: str | None = Field(
        None, description="La phrase du texte qui porte la position, recopiée exactement")


SYSTEM = (
    "Tu lis une prise de parole politique publiée sur X et tu dis si son auteur y "
    "prend position sur une question précise. Tu ne sais pas qui est l'auteur, et "
    "tu ne dois pas chercher à le deviner.\n\n"
    "Règles :\n"
    "- Seule compte la position de l'auteur. Une position qu'il rapporte, critique "
    "ou attribue à d'autres n'est pas la sienne.\n"
    "- Attaquer un adversaire n'est pas prendre position, sauf si le texte dit "
    "clairement ce que l'auteur veut à la place.\n"
    "- « explicite » : la position est dite. « implicite » : elle se déduit du "
    "texte sans hésitation. Si tu dois deviner, prend_position = false.\n"
    "- Choisis un code de l'échelle, et uniquement un code de l'échelle.\n"
    "- verbatim : recopie à l'identique, sans rien corriger, la phrase du texte de "
    "l'auteur qui porte la position. Jamais une phrase du tweet cité."
)


def signature(model: str) -> str:
    return f"{ENJEUX_VERSION}/{model}"[:120]


def prompt_for(enjeu: Enjeu, texte: str, cite: str | None = None) -> str:
    echelle = "\n".join(f"- {c.code} : {c.label}" for c in enjeu.echelle)
    out = (f"Question : {enjeu.question}\n\nÉchelle :\n{echelle}\n\n"
           f"Texte de l'auteur :\n«««\n{texte.strip()[:2000]}\n»»»")
    if cite:
        out += (f"\n\nTweet cité par l'auteur (écrit par quelqu'un d'autre, "
                f"contexte seulement) :\n«««\n{cite.strip()[:800]}\n»»»")
    return out


def valider(enjeu: Enjeu, lue: PositionLue, texte: str) -> tuple[str | None, str | None, str | None]:
    """Ce qui s'écrit en base : (position, certitude, verbatim), ou trois None.

    Un cran hors échelle ou un verbatim introuvable dans le texte annulent la
    position. Le post reste marqué lu : on ne repaie pas une réponse fausse.
    """
    if not lue.prend_position or not enjeu.cran(lue.position):
        return None, None, None
    if not lue.verbatim or not verbatim_in_source(lue.verbatim, texte):
        return None, None, None
    return lue.position, lue.certitude or "explicite", lue.verbatim.strip()


def _a_lire(enjeu: Enjeu):
    deja = exists().where(and_(Position.post_id == Post.id, Position.enjeu == enjeu.slug))
    return and_(
        Post.is_retweet.isnot(True),
        or_(Post.post_type.is_(None), Post.post_type != "retweet"),
        or_(*[func.lower(Post.content).like(f"%{a}%") for a in enjeu.amorces]),
        ~deja,
    )


async def lire_positions(*, limit: int = 400) -> dict:
    """Une passe sur tous les enjeux. Idempotente, reprenable, bornée."""
    from src.services.analysis.claim_llm import get_claim_llm

    llm = get_claim_llm()
    if not llm.available():
        return {"skipped": "aucun modèle de tier 2 configuré"}
    lecteur = signature(llm._s.claim_tier2_model)
    factory = get_session_factory()
    stats: dict[str, dict] = {}
    budget_hit = False

    for enjeu in ENJEUX:
        if budget_hit:
            break
        async with factory() as db:
            posts = list((await db.execute(
                select(Post).where(_a_lire(enjeu))
                .order_by(Post.published_at.asc().nullslast()).limit(limit)
            )).scalars().all())
        s = {"lus": 0, "positions": 0, "rejetes": 0, "echecs": 0}
        for post in posts:
            # Les amorces SQL ratissent large (« russ » prend « Russell ») ;
            # l'expression régulière tranche avant de payer un appel.
            if not enjeu.concerne(post.content):
                pos = cert = verb = None
            else:
                try:
                    lue = await llm.read_position(
                        prompt=prompt_for(enjeu, post.content, post.quoted_content),
                        system=SYSTEM, schema=PositionLue)
                except BudgetExceeded as exc:
                    logger.warning("positions.budget_exceeded", detail=str(exc))
                    budget_hit = True
                    break
                except ProviderRefused:
                    raise
                except Exception as exc:  # noqa: BLE001
                    logger.warning("positions.read_failed", post_id=post.id, error=str(exc)[:120])
                    s["echecs"] += 1
                    continue
                if lue is None:
                    # Appel raté : rien n'est écrit, le post repassera.
                    s["echecs"] += 1
                    continue
                pos, cert, verb = valider(enjeu, lue, post.content)
                if lue.prend_position and pos is None:
                    s["rejetes"] += 1
            async with factory() as db:
                db.add(Position(
                    post_id=post.id, personality_id=post.personality_id, enjeu=enjeu.slug,
                    position=pos, certitude=cert, verbatim=verb,
                    published_at=post.published_at, lecteur=lecteur,
                ))
                await db.commit()
            s["lus"] += 1
            s["positions"] += pos is not None
        stats[enjeu.slug] = s

    logger.info("positions.done", budget_exceeded=budget_hit, **{k: str(v) for k, v in stats.items()})
    return {"enjeux": stats, "budget_exceeded": budget_hit, "lecteur": lecteur}


# ── Lecture, pour les fiches ─────────────────────────────────────────────

async def fiche(db, slug: str) -> dict | None:
    """La fiche d'un enjeu : la trajectoire de chaque figure, et ses écarts."""
    enjeu = PAR_SLUG.get(slug)
    if enjeu is None:
        return None
    rows = (await db.execute(
        select(Position, Post, Personality)
        .join(Post, Post.id == Position.post_id)
        .join(Personality, Personality.id == Position.personality_id)
        .where(Position.enjeu == slug, Position.position.isnot(None))
        .order_by(Position.published_at.asc())
    )).all()

    figures: dict[int, dict] = {}
    points: list[Point] = []
    par_post: dict[int, dict] = {}
    for pos, post, pers in rows:
        f = figures.setdefault(pers.id, {
            "id": pers.id, "nom": pers.full_name, "handle": pers.handle,
            "groupe": pers.group_code, "positions": [],
        })
        item = {
            "post_id": post.id, "date": pos.published_at.isoformat() if pos.published_at else None,
            "position": pos.position, "label": enjeu.cran(pos.position).label,
            "rang": enjeu.cran(pos.position).rang, "certitude": pos.certitude,
            "verbatim": pos.verbatim, "url": post.url, "recu": post.snapshot_url,
        }
        f["positions"].append(item)
        par_post[post.id] = item
        if pos.published_at:
            points.append(Point(pers.id, pos.position, pos.published_at, post.id))

    liste = sorted(figures.values(), key=lambda f: -len(f["positions"]))
    return {
        "slug": enjeu.slug, "titre": enjeu.titre, "question": enjeu.question,
        "echelle": [{"code": c.code, "label": c.label, "rang": c.rang} for c in enjeu.echelle],
        "jalons": list(enjeu.jalons),
        "figures": liste,
        "ecarts": [
            {"figure": figures[e.personality_id]["nom"], "figure_id": e.personality_id,
             "ampleur": e.ampleur, "avant": par_post[e.avant.post_id],
             "apres": par_post[e.apres.post_id]}
            for e in ecarts(enjeu, points)
        ],
    }


async def sommaire(db) -> list[dict]:
    """Les enjeux du registre, avec ce que la base contient pour chacun."""
    counts = {slug: (n, f) for slug, n, f in (await db.execute(
        select(Position.enjeu, func.count(), func.count(func.distinct(Position.personality_id)))
        .where(Position.position.isnot(None)).group_by(Position.enjeu)
    )).all()}
    lus = dict((await db.execute(
        select(Position.enjeu, func.count()).group_by(Position.enjeu))).all())
    return [
        {"slug": e.slug, "titre": e.titre, "question": e.question,
         "positions": counts.get(e.slug, (0, 0))[0], "figures": counts.get(e.slug, (0, 0))[1],
         "lus": lus.get(e.slug, 0)}
        for e in ENJEUX
    ]
