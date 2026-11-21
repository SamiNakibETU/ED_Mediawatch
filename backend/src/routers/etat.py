"""L'état de la chaîne, pour la page Coulisses : collecte, registre, écarts, archivage, dépense, couverture."""

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database import get_db
from src.models.declaration import Declaration
from src.models.ecart import Ecart
from src.models.llm_usage import LlmUsageEvent
from src.models.post import Post
from src.services.collection.couverture import couverture

router = APIRouter(prefix="/etat", tags=["etat"])

VOIES = {"xitter": "recherche datée sur une instance Nitter (historique)",
         "xitter-p": "pages de profil sur xitter.cf",
         "comptes": "comptes de recherche",
         "synd": "intégration publique de X", "syndfx": "intégration publique de X",
         "fxtw": "fxtwitter (textes complets)"}


@router.get("")
async def get_etat(db: AsyncSession = Depends(get_db)) -> dict:
    voies = [{"voie": v or "?", "libelle": VOIES.get(v or "", v or "?"), "tweets": n, "dernier": d}
             for v, n, d in (await db.execute(
                 select(Post.collected_via, func.count(), func.max(Post.published_at))
                 .group_by(Post.collected_via).order_by(func.count().desc()))).all()]
    tweets, dernier = (await db.execute(select(func.count(), func.max(Post.published_at)))).one()
    lus = await db.scalar(select(func.count()).where(Post.decl_lu.isnot(None)))

    valide = or_(Declaration.douteuse.is_(None), Declaration.douteuse.is_(False))
    decl = {
        "total": await db.scalar(select(func.count(Declaration.id))),
        "avec_position": await db.scalar(select(func.count()).where(Declaration.position.isnot(None), valide)),
        "douteuses": await db.scalar(select(func.count()).where(Declaration.douteuse.is_(True))),
        "sans_position": await db.scalar(select(func.count()).where(Declaration.position.is_(None))),
    }
    ecarts: dict[str, dict[str, int]] = {}
    for t, a, n in (await db.execute(select(Ecart.type, Ecart.auto, func.count()).group_by(Ecart.type, Ecart.auto))).all():
        ecarts.setdefault(t, {})[a or "attente"] = n

    preuves = select(Declaration.post_id).where(Declaration.position.isnot(None), valide).distinct().subquery()
    a_archiver = await db.scalar(select(func.count()).select_from(preuves))
    archives = await db.scalar(select(func.count()).select_from(Post).join(preuves, preuves.c.post_id == Post.id)
                               .where(Post.snapshot_url.isnot(None)))

    depuis = datetime.now(timezone.utc) - timedelta(days=30)
    depense = [{"tache": t, "modele": m, "appels": n, "cout": round(c or 0, 3)} for t, m, n, c in (await db.execute(
        select(LlmUsageEvent.task, LlmUsageEvent.model, func.count(), func.sum(LlmUsageEvent.cost_usd))
        .where(LlmUsageEvent.ts >= depuis).group_by(LlmUsageEvent.task, LlmUsageEvent.model)
        .order_by(func.sum(LlmUsageEvent.cost_usd).desc()))).all()]

    cov = await couverture(db)
    nb_mois = len(cov["mois"])
    figures = sorted(
        ({"id": f["id"], "nom": f["nom"], "groupe": f["groupe"], "tweets": f["en_base_depuis"],
          "mois_couverts": nb_mois - f["mois_vides"]} for f in cov["figures"]),
        key=lambda f: (-f["mois_couverts"], -f["tweets"]))
    return {
        "collecte": {"tweets": tweets, "dernier_tweet": dernier, "voies": voies},
        "registre": {"tweets_lus": lus, **decl},
        "ecarts": ecarts,
        "archivage": {"tweets_a_archiver": a_archiver, "archives": archives},
        "depense_30_jours": {"total": round(sum(d["cout"] for d in depense), 2), "detail": depense},
        "couverture": {"depuis": cov["depuis"], "mois": nb_mois, "figures": figures},
    }
