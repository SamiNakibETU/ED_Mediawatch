"""ED_Mediawatch API — X collection slice.

Veille quotidienne des prises de parole de l'extrême droite (RN/UDR + figures)
sur X, via Nitter. Socle réutilisé de breve_de_presse_PMO, étendu plus tard à
la presse + classification thématique + détection d'incohérences.
"""

from contextlib import asynccontextmanager
from pathlib import Path

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from src.config import get_settings
from src.database import init_db
from src.routers import (
    articles,
    classification,
    compteur,
    contradictions,
    health,
    meta,
    personalities,
    posts,
    referentiel,
)
from src.services.collection.x_collector import run_collection
from src.services.scheduler import create_scheduler

logger = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    await init_db()
    logger.info("db.ready", url=settings.database_url.split("://")[0])

    scheduler = create_scheduler()
    scheduler.start()
    app.state.scheduler = scheduler

    if settings.collect_on_startup:
        logger.info("startup.collect")
        try:
            await run_collection()
        except Exception as exc:  # noqa: BLE001
            logger.warning("startup.collect_failed", error=str(exc)[:200])

    yield

    scheduler.shutdown(wait=False)


app = FastAPI(title="ED_Mediawatch API", version="0.1.0", lifespan=lifespan)

_cors = {"allow_methods": ["*"], "allow_headers": ["*"]}
if get_settings().cors_origins.strip():
    # Prod : liste blanche explicite d'origines (CSV).
    _cors["allow_origins"] = [o.strip() for o in get_settings().cors_origins.split(",") if o.strip()]
else:
    # Dev : front servi sur n'importe quel port localhost (3000, 3001…).
    _cors["allow_origin_regex"] = r"http://(localhost|127\.0\.0\.1):\d+"
app.add_middleware(CORSMiddleware, **_cors)

app.include_router(health.router)
app.include_router(meta.router)
app.include_router(personalities.router)
app.include_router(posts.router)
app.include_router(articles.router)
app.include_router(referentiel.router)
app.include_router(classification.router)
app.include_router(compteur.router)
app.include_router(contradictions.router)

# Front statique servi par le backend (même origine → pas de CORS, une seule URL).
# Monté en dernier : les routes API ci-dessus ont la priorité ; tout le reste
# (`/`, `/compteur.html`, `/app.js`…) est servi depuis backend/static.
_static_dir = Path(__file__).resolve().parent.parent / "static"
if _static_dir.is_dir():
    app.mount("/", StaticFiles(directory=str(_static_dir), html=True), name="static")
