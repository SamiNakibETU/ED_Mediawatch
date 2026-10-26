"""De quoi parle l'extrême droite sur X : courbes par thème, tweets d'un moment, sujets de la semaine."""

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database import get_db
from src.models.declaration import Declaration
from src.models.personality import Personality
from src.models.post import Post
from src.models.sujet_semaine import SujetSemaine
from src.services.analysis.enjeux import PAR_SLUG, THEMES
from src.services.analysis.themes import PAS, serie

router = APIRouter(prefix="/themes", tags=["themes"])


def _periode(debut: str | None, fin: str | None, jours: int) -> tuple[datetime, datetime]:
    f = datetime.fromisoformat(fin).replace(tzinfo=timezone.utc) if fin else datetime.now(timezone.utc)
    d = datetime.fromisoformat(debut).replace(tzinfo=timezone.utc) if debut else f - timedelta(days=jours)
    return d, f


@router.get("/serie")
async def get_serie(
    pas: str = Query("jour"), debut: str | None = None, fin: str | None = None,
    parti: str | None = None, figure: int | None = None, retweets: bool = True,
    db: AsyncSession = Depends(get_db),
) -> dict:
    if pas not in PAS:
        raise HTTPException(400, f"pas inconnu : {pas}")
    defaut = {"heure": 3, "jour": 60, "semaine": 365, "mois": 1500}[pas]
    d, f = _periode(debut, fin, defaut)
    return await serie(db, pas=pas, debut=d, fin=f, parti=parti, figure_id=figure, retweets=retweets)


def _tweet(post: Post, pers: Personality, decls: list[Declaration]) -> dict:
    return {
        "id": post.id, "figure": pers.full_name, "figure_id": pers.id, "groupe": pers.group_code,
        "theme": post.theme_ed,
        "source": {"kind": "tweet", "url": post.url, "text": post.content, "published_at": post.published_at,
                   "archive": post.snapshot_url, "author": pers.handle, "post_type": post.post_type,
                   "quoted_author": post.quoted_handle, "quoted_text": post.quoted_content,
                   "truncated": bool(post.text_truncated)},
        "declarations": [
            {"enjeu": d.enjeu, "titre": PAR_SLUG[d.enjeu].titre if d.enjeu in PAR_SLUG else None,
             "position": (PAR_SLUG[d.enjeu].cran(d.position).label
                          if d.enjeu in PAR_SLUG and PAR_SLUG[d.enjeu].cran(d.position) else None),
             "objet": d.objet, "verbatim": d.verbatim, "modalite": d.modalite}
            for d in decls],
    }


async def _avec_declarations(db, rows) -> list[dict]:
    ids = [p.id for p, _ in rows]
    decls: dict[int, list] = {}
    if ids:
        for d in (await db.execute(select(Declaration).where(Declaration.post_id.in_(ids)))).scalars():
            decls.setdefault(d.post_id, []).append(d)
    return [_tweet(p, pers, decls.get(p.id, [])) for p, pers in rows]


@router.get("/tweets")
async def get_tweets(
    debut: str, fin: str, theme: str | None = None, parti: str | None = None,
    figure: int | None = None, limit: int = Query(60, le=200), db: AsyncSession = Depends(get_db),
) -> dict:
    """Les tweets d'un moment : ce qu'il y a derrière un point de la courbe."""
    d, f = _periode(debut, fin, 1)
    stmt = (select(Post, Personality).join(Personality, Personality.id == Post.personality_id)
            .where(Post.published_at >= d, Post.published_at < f))
    if theme:
        stmt = stmt.where(Post.theme_ed == theme)
    if parti:
        stmt = stmt.where(Personality.group_code == parti)
    if figure:
        stmt = stmt.where(Post.personality_id == figure)
    rows = (await db.execute(stmt.order_by(Post.published_at.desc()).limit(limit))).all()
    return {"items": await _avec_declarations(db, rows)}


@router.get("/sujets")
async def get_sujets(semaine: str | None = None, db: AsyncSession = Depends(get_db)) -> dict:
    """Les sujets d'une semaine (la dernière calculée par défaut), et les semaines disponibles."""
    semaines = [s for (s,) in (await db.execute(
        select(SujetSemaine.semaine).distinct().order_by(SujetSemaine.semaine.desc()))).all()]
    choisie = semaine or (semaines[0] if semaines else None)
    sujets = [] if not choisie else (await db.execute(
        select(SujetSemaine).where(SujetSemaine.semaine == choisie).order_by(SujetSemaine.ordre))).scalars().all()
    return {"semaine": choisie, "semaines": semaines, "themes": THEMES,
            "sujets": [{"id": s.id, "libelle": s.libelle, "theme": s.theme, "n_tweets": s.n_tweets,
                        "n_figures": s.n_figures} for s in sujets]}


@router.get("/sujets/{sujet_id}")
async def get_sujet(sujet_id: int, db: AsyncSession = Depends(get_db)) -> dict:
    s = await db.get(SujetSemaine, sujet_id)
    if s is None:
        raise HTTPException(404, "sujet inconnu")
    rows = (await db.execute(
        select(Post, Personality).join(Personality, Personality.id == Post.personality_id)
        .where(Post.id.in_(s.post_ids or [])).order_by(Post.published_at))).all()
    return {"libelle": s.libelle, "semaine": s.semaine, "theme": s.theme, "items": await _avec_declarations(db, rows)}
