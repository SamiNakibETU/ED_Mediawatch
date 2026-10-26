"""Lecture du registre pour les pages : la fiche d'un enjeu, le sommaire des enjeux.

Les déclarations sont écrites par `registre.py`. Ici, on les assemble : la
trajectoire de chaque figure sur l'échelle, les écarts qui s'en déduisent, et
le tweet de chaque point, pour qu'aucune position ne s'affiche sans sa source.
"""

from __future__ import annotations

from sqlalchemy import func, select

from src.models.declaration import Declaration
from src.models.engagement_programme import EngagementProgramme
from src.models.personality import Personality
from src.models.post import Post
from src.services.analysis.enjeux import ENJEUX, HORS_LISTE, PAR_SLUG, THEMES, Point, ecarts


def _source(post: Post, handle: str | None) -> dict:
    return {"kind": "tweet", "url": post.url, "text": post.content, "published_at": post.published_at,
            "archive": post.snapshot_url, "author": handle, "post_type": post.post_type,
            "quoted_author": post.quoted_handle, "quoted_text": post.quoted_content,
            "truncated": bool(post.text_truncated)}


async def fiche(db, slug: str) -> dict | None:
    """La fiche d'un enjeu : la trajectoire de chaque figure, et ses écarts."""
    enjeu = PAR_SLUG.get(slug)
    if enjeu is None:
        return None
    rows = (await db.execute(
        select(Declaration, Post, Personality)
        .join(Post, Post.id == Declaration.post_id)
        .join(Personality, Personality.id == Declaration.personality_id)
        .where(Declaration.enjeu == slug, Declaration.position.isnot(None))
        .order_by(Declaration.published_at.asc())
    )).all()

    figures: dict[int, dict] = {}
    points: list[Point] = []
    par_decl: dict[int, dict] = {}
    for d, post, pers in rows:
        cran = enjeu.cran(d.position)
        if cran is None:
            continue
        f = figures.setdefault(pers.id, {
            "id": pers.id, "nom": pers.full_name, "handle": pers.handle,
            "groupe": pers.group_code, "positions": [],
        })
        item = {
            "post_id": post.id, "decl_id": d.id,
            "date": d.published_at.isoformat() if d.published_at else None,
            "position": d.position, "label": cran.label, "rang": cran.rang,
            "certitude": d.certitude, "modalite": d.modalite,
            "valeur": d.valeur, "unite": d.unite,
            "verbatim": d.verbatim, "url": post.url, "recu": post.snapshot_url,
            "source": _source(post, pers.handle),
        }
        f["positions"].append(item)
        par_decl[d.id] = item
        if d.published_at:
            # Le point porte l'identifiant de la déclaration : un tweet peut en
            # porter deux, sur deux enjeux.
            points.append(Point(pers.id, d.position, d.published_at, d.id))

    liste = sorted(figures.values(), key=lambda f: -len(f["positions"]))

    # Le programme de chaque parti sur cet enjeu, et les déclarations de ses
    # figures qui s'en écartent. On ne compare qu'à son propre camp, et
    # seulement après la publication du programme : avant, il n'existait pas.
    prog_rows = (await db.execute(
        select(EngagementProgramme)
        .where(EngagementProgramme.enjeu == slug, EngagementProgramme.position.isnot(None))
        .order_by(EngagementProgramme.annee, EngagementProgramme.livret, EngagementProgramme.page)
    )).scalars().all()
    programme = [
        {"parti": e.parti, "annee": e.annee, "source": e.source, "position": e.position,
         "label": enjeu.cran(e.position).label, "rang": enjeu.cran(e.position).rang,
         "verbatim": e.verbatim, "livret": e.livret, "page": e.page, "modalite": e.modalite}
        for e in prog_rows if enjeu.cran(e.position)
    ]
    crans_programme: dict[tuple[str, int], set[str]] = {}
    for e in programme:
        crans_programme.setdefault((e["parti"], e["annee"]), set()).add(e["position"])
    ecarts_programme = []
    for f in liste:
        for (parti, annee), crans in crans_programme.items():
            if f["groupe"] != parti:
                continue
            for p in f["positions"]:
                if p["position"] not in crans and p["date"] and int(p["date"][:4]) >= annee:
                    ecarts_programme.append({
                        "figure": f["nom"], "figure_id": f["id"], "parti": parti, "annee": annee,
                        "declaration": p,
                        "programme": [e for e in programme if e["parti"] == parti and e["annee"] == annee],
                    })
    ecarts_programme.sort(key=lambda x: x["declaration"]["date"] or "", reverse=True)

    return {
        "programme": programme,
        "ecarts_programme": ecarts_programme,
        "slug": enjeu.slug, "titre": enjeu.titre, "question": enjeu.question,
        "theme": enjeu.theme, "theme_label": THEMES.get(enjeu.theme, enjeu.theme),
        "echelle": [{"code": c.code, "label": c.label, "rang": c.rang} for c in enjeu.echelle],
        "jalons": list(enjeu.jalons),
        "figures": liste,
        "ecarts": [
            {"figure": figures[e.personality_id]["nom"], "figure_id": e.personality_id,
             "ampleur": e.ampleur, "avant": par_decl[e.avant.post_id], "apres": par_decl[e.apres.post_id]}
            for e in ecarts(enjeu, points)
        ],
    }


async def sommaire(db) -> list[dict]:
    """Les enjeux du référentiel, avec ce que le registre contient pour chacun.

    L'ordre est celui du référentiel, par thème : un sommaire trié par volume
    mettrait en tête ce dont on parle le plus, pas ce qui se compare le mieux.
    """
    counts = {slug: (n, f) for slug, n, f in (await db.execute(
        select(Declaration.enjeu, func.count(), func.count(func.distinct(Declaration.personality_id)))
        .where(Declaration.position.isnot(None)).group_by(Declaration.enjeu)
    )).all()}
    return [
        {"slug": e.slug, "titre": e.titre, "question": e.question, "theme": e.theme,
         "theme_label": THEMES.get(e.theme, e.theme),
         "positions": counts.get(e.slug, (0, 0))[0], "figures": counts.get(e.slug, (0, 0))[1]}
        for e in ENJEUX
    ]


async def hors_liste(db, *, limit: int = 60) -> list[dict]:
    """Les objets les plus fréquents parmi les déclarations hors liste.

    C'est la liste des questions qui manquent au référentiel : un objet qui
    revient chez plusieurs figures mérite sa propre question.
    """
    rows = (await db.execute(
        select(func.lower(Declaration.objet), func.count(),
               func.count(func.distinct(Declaration.personality_id)))
        .where(Declaration.enjeu == HORS_LISTE, Declaration.objet.isnot(None))
        .group_by(func.lower(Declaration.objet))
        .order_by(func.count(func.distinct(Declaration.personality_id)).desc(), func.count().desc())
        .limit(limit)
    )).all()
    return [{"objet": o, "declarations": n, "figures": f} for o, n, f in rows]
