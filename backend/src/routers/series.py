"""Les séries mensuelles — la brique qui manquait pour « comparer dans la durée ».

Le produit annonce depuis le début qu'il suit le propos dans la DURÉE, et
n'affichait aucune série temporelle : la frise d'un sujet, et rien d'autre. Un
observatoire qui promet la comparaison dans le temps et ne montre jamais le
temps demande qu'on le croie sur parole.

Ce que ces séries mesurent, et ce qu'elles ne mesurent pas. Elles comptent des
déclarations ATTRIBUÉES, mois par mois : rien de plus qu'une addition sur des
données vérifiées à l'extraction. Aucun jugement de modèle n'entre dans la
hauteur d'une barre — c'est ce qui les rend publiables, là où la répartition
thématique attend encore un second annotateur (α = 0,599).

Le mois est le grain juste. À la semaine, le bruit de la collecte domine — un
week-end sans tweet creuse un trou qui ne veut rien dire. À l'année, un
revirement de trois mois disparaît.

CE QUI A FAILLI ÊTRE PUBLIÉ COMME UN FAIT. Mesuré le 03/09/2026 sur le corpus :
mars 2026 compte 9 publications, août 2026 en compte 2 097. Dessinées sur le
même axe, ces deux barres racontent une explosion du discours. Elles racontent
en réalité le début de la veille : AVANT AOÛT 2026, TOUT A ÉTÉ RECONSTITUÉ APRÈS
COUP (Wayback, fxtwitter), donc partiellement. Un observatoire qui présente sa
propre montée en charge comme une montée du discours qu'il observe se
discrédite d'un seul graphique.

D'où `retro` : pour chaque mois, combien de ses déclarations viennent d'une
source collectée plus de trente jours après sa publication. Un mois
majoritairement rétrospectif est un PLANCHER, pas une mesure, et la page doit le
dessiner autrement. `veille_depuis` donne le mois à partir duquel on regardait
en continu — la seule portion du graphique dont on peut tirer une tendance.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database import get_db
from src.models.article import Article
from src.models.claim import Claim
from src.models.contradiction import Contradiction
from src.models.personality import Personality
from src.models.post import Post

router = APIRouter(prefix="/series", tags=["series"])

# Au-delà de trente jours entre la publication et la collecte, ce n'est plus de
# la veille, c'est de l'archéologie : on n'a pas vu passer le propos, on est
# allé le chercher, et on n'a aucune garantie de l'avoir trouvé en entier.
RETARD_RETRO_JOURS = 30
# Un mois dont plus de la moitié a été rattrapée après coup ne se compare pas à
# un mois surveillé. Le seuil est franc parce que la réalité l'est : sur ce
# corpus, les mois sont à 0 % ou à 100 %.
SEUIL_RETRO = 0.5
# Trois ans : le cycle électoral entier, et des barres encore lisibles. Au-delà
# (le corpus remonte à 2018, soit 101 mois), chaque barre fait un pixel de large
# et le graphique ne dit plus rien.
FENETRE_MOIS = 36


def _mois(quand: datetime) -> str:
    return quand.strftime("%Y-%m")


def _combler(points: dict[str, dict], depuis: str, jusqu: str) -> list[dict]:
    """Tous les mois entre le premier et le dernier, y compris les vides.

    Un mois sans prise de parole est une information — il s'est tu — et le
    sauter écraserait l'axe : deux barres voisines seraient à six mois d'écart
    sans que rien ne le dise.
    """
    an, mois = (int(x) for x in depuis.split("-"))
    fin_an, fin_mois = (int(x) for x in jusqu.split("-"))
    out: list[dict] = []
    while (an, mois) <= (fin_an, fin_mois):
        cle = f"{an:04d}-{mois:02d}"
        out.append(points.get(cle)
                   or {"mois": cle, "n": 0, "contradictions": 0, "retro": 0})
        mois += 1
        if mois == 13:
            an, mois = an + 1, 1
    return out


def _veille_depuis(points: list[dict]) -> str | None:
    """Le premier mois d'une suite ININTERROMPUE de mois surveillés, en partant
    de la fin. Un mois surveillé isolé au milieu du rattrapage ne fonde rien."""
    debut = None
    for p in reversed(points):
        # Un mois vide ne prouve rien — ni qu'on regardait, ni le contraire. Il
        # ne fait pas remonter la date de début : dire « veille continue depuis
        # février » sur la foi d'un février sans aucune donnée serait un
        # surclassement de ce qu'on sait.
        if p["n"] == 0:
            continue
        if p["retro"] / p["n"] > SEUIL_RETRO:
            break
        debut = p["mois"]
    return debut


def _borne(mois: int) -> datetime:
    """Le premier jour du mois, `mois` mois en arrière."""
    debut = datetime.now(timezone.utc).replace(day=1)
    an, m = debut.year, debut.month - (mois - 1)
    while m <= 0:
        an, m = an - 1, m + 12
    return datetime(an, m, 1, tzinfo=timezone.utc)


async def _serie(db: AsyncSession, *, ids_claims_filter) -> dict:
    """Compte par mois ; marque les contradictions et ce qui a été rattrapé."""
    rows = (await db.execute(
        select(Claim.id, Claim.published_at, Post.created_at, Article.created_at)
        .outerjoin(Post, Post.id == Claim.post_id)
        .outerjoin(Article, Article.id == Claim.article_id)
        .where(Claim.published_at.isnot(None), Claim.speaker_name.isnot(None),
               *ids_claims_filter)
    )).all()
    if not rows:
        return {"points": [], "total": 0, "veille_depuis": None}

    par_mois: dict[str, dict] = {}
    mois_de = {}
    for cid, quand, collecte_post, collecte_art in rows:
        m = _mois(quand)
        mois_de[cid] = m
        e = par_mois.setdefault(m, {"mois": m, "n": 0, "contradictions": 0,
                                    "retro": 0})
        e["n"] += 1
        collecte = collecte_post or collecte_art
        if collecte is not None:
            retard = (collecte.replace(tzinfo=None) - quand.replace(tzinfo=None)).days
            if retard > RETARD_RETRO_JOURS:
                e["retro"] += 1

    # Les contradictions retenues, rattachées au mois de chacune de leurs deux
    # déclarations : un revirement se lit aux deux bouts.
    concernes = set(mois_de)
    for a, b in (await db.execute(
        select(Contradiction.claim_a_id, Contradiction.claim_b_id)
        .where(Contradiction.status != "rejected")
    )).all():
        for cid in (a, b):
            if cid in concernes:
                par_mois[mois_de[cid]]["contradictions"] += 1

    cles = sorted(par_mois)
    points = _combler(par_mois, cles[0], cles[-1])
    return {
        "points": points,
        "total": sum(e["n"] for e in par_mois.values()),
        "veille_depuis": _veille_depuis(points),
    }


@router.get("/figure/{figure_id}")
async def serie_figure(
    figure_id: int,
    mois: int = Query(FENETRE_MOIS, ge=3, le=180, description="Profondeur en mois"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Quand ce locuteur parle, et quand on lui a trouvé une contradiction."""
    p = await db.get(Personality, figure_id)
    if p is None:
        raise HTTPException(404, "locuteur inconnu")
    # Par identifiant OU par nom : la presse attribue par nom, X par compte, et
    # les deux voix sont la même personne dans une comparaison.
    filtre = (or_(Claim.personality_id == figure_id,
                  Claim.speaker_name == p.full_name),
              Claim.published_at >= _borne(mois))
    return {"figure": p.full_name, "fenetre_mois": mois,
            **await _serie(db, ids_claims_filter=filtre)}


@router.get("/corpus")
async def serie_corpus(
    mois: int = Query(FENETRE_MOIS, ge=3, le=180, description="Profondeur en mois"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Le pouls du fonds : tout ce qui a été consigné, mois par mois."""
    return {"fenetre_mois": mois,
            **await _serie(db, ids_claims_filter=(Claim.published_at >= _borne(mois),))}
