from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.database import get_db
from src.models.article import Article
from src.models.post import Post
from src.models.referentiel import Subtheme, Theme
from src.models.taxonomy import Actualite, Sujet
from src.schemas import ActualiteIn, ActualiteOut, SujetIn, SujetOut
from src.security import require_token
from src.services.analysis.embeddings import (
    embed_referents,
    fusion_candidates,
    nearest_referent,
)
from src.utils import slugify

router = APIRouter(tags=["referentiel"])


@router.get("/referentiel")
async def get_referentiel(db: AsyncSession = Depends(get_db)) -> dict:
    res = await db.execute(
        select(Theme)
        .options(selectinload(Theme.subthemes).selectinload(Subtheme.referents))
        .order_by(Theme.order)
    )
    themes = res.scalars().unique().all()
    out = []
    for t in themes:
        subs = []
        for st in t.subthemes:
            subs.append({
                "id": st.id, "label": st.label,
                "referents": [
                    {"key": r.key, "label": r.label, "unit": r.unit}
                    for r in st.referents
                ],
            })
        out.append({
            "id": t.id, "label": t.label, "order": t.order,
            "code": t.code, "salience": t.salience, "subthemes": subs,
        })
    version = themes[0].version if themes else None
    return {"version": version, "themes": out}


async def _counts(db: AsyncSession, column) -> dict[str, int]:
    """Compte les items par valeur de `column` (Post.theme, Article.subtheme…)."""
    rows = (
        await db.execute(
            select(column, func.count()).where(column.isnot(None)).group_by(column)
        )
    ).all()
    return {k: n for k, n in rows}


@router.get("/themes/tree")
async def themes_tree(db: AsyncSession = Depends(get_db)) -> dict:
    """Arbre de navigation Thème → Sous-thème avec compteurs par source (X/presse).

    Alimente la navigation thématique des deux surfaces (§8). Les thèmes vides
    (backbone CAP sans item) sont marqués `empty` pour que le front puisse les
    masquer ou les griser.
    """
    res = await db.execute(
        select(Theme).options(selectinload(Theme.subthemes)).order_by(Theme.order)
    )
    themes = res.scalars().unique().all()

    pt, at = await _counts(db, Post.theme), await _counts(db, Article.theme)
    ps, as_ = await _counts(db, Post.subtheme), await _counts(db, Article.subtheme)

    out = []
    for t in themes:
        subs = [
            {
                "id": st.id, "label": st.label,
                "posts": ps.get(st.id, 0), "articles": as_.get(st.id, 0),
            }
            for st in sorted(t.subthemes, key=lambda s: s.label)
        ]
        posts, articles = pt.get(t.id, 0), at.get(t.id, 0)
        out.append({
            "id": t.id, "label": t.label, "code": t.code, "salience": t.salience,
            "order": t.order, "posts": posts, "articles": articles,
            "empty": (posts + articles) == 0, "subthemes": subs,
        })
    return {"themes": out}


# --- Sujets (persistants) ---------------------------------------------------


@router.get("/sujets", response_model=list[SujetOut])
async def list_sujets(
    theme: str | None = Query(None, description="theme_id"),
    db: AsyncSession = Depends(get_db),
) -> list[Sujet]:
    stmt = select(Sujet).order_by(Sujet.label)
    if theme:
        stmt = stmt.where(Sujet.theme_id == theme)
    return list((await db.execute(stmt)).scalars().all())


@router.post("/sujets", response_model=SujetOut, dependencies=[Depends(require_token)])
async def create_sujet(body: SujetIn, db: AsyncSession = Depends(get_db)) -> Sujet:
    slug = body.slug or slugify(body.label)
    if await db.scalar(select(Sujet.id).where(Sujet.slug == slug)):
        raise HTTPException(409, f"sujet déjà existant : {slug}")
    sujet = Sujet(
        slug=slug, label=body.label, description=body.description,
        theme_id=body.theme_id, subtheme_id=body.subtheme_id,
    )
    db.add(sujet)
    await db.commit()
    await db.refresh(sujet)
    return sujet


# --- Actualités (datées) ----------------------------------------------------


@router.get("/actualites", response_model=list[ActualiteOut])
async def list_actualites(
    theme: str | None = Query(None, description="theme_id"),
    db: AsyncSession = Depends(get_db),
) -> list[Actualite]:
    stmt = select(Actualite).order_by(Actualite.event_date.desc().nullslast())
    if theme:
        stmt = stmt.where(Actualite.theme_id == theme)
    return list((await db.execute(stmt)).scalars().all())


@router.post("/actualites", response_model=ActualiteOut, dependencies=[Depends(require_token)])
async def create_actualite(body: ActualiteIn, db: AsyncSession = Depends(get_db)) -> Actualite:
    slug = body.slug or slugify(body.label)
    if await db.scalar(select(Actualite.id).where(Actualite.slug == slug)):
        raise HTTPException(409, f"actualité déjà existante : {slug}")
    actu = Actualite(
        slug=slug, label=body.label, description=body.description,
        theme_id=body.theme_id, event_date=body.event_date,
    )
    db.add(actu)
    await db.commit()
    await db.refresh(actu)
    return actu


@router.post("/embed-referents", dependencies=[Depends(require_token)])
async def post_embed_referents() -> dict:
    """Calcule/cache les embeddings Cohere des référents (idempotent)."""
    return await embed_referents()


@router.get("/referent-neighbors")
async def referent_neighbors(
    sentence: str = Query(..., description="phrase à rattacher au référent le plus proche"),
    top: int = Query(3, ge=1, le=10),
) -> dict:
    return {"sentence": sentence, "matches": await nearest_referent(sentence, top=top)}


@router.get("/referent-fusion")
async def referent_fusion(threshold: float = Query(0.86, ge=0.5, le=1.0)) -> dict:
    """Référents sémantiquement redondants (candidats à fusion/curation)."""
    return {"threshold": threshold, "candidates": await fusion_candidates(threshold)}
