# ED · MediaWatch

Veille continue des prises de parole de l'extrême droite française (RN, UDR,
Reconquête, mouvance) sur X et dans la presse en ligne, en vue de 2027.
Collecte, archivage, extraction d'assertions chiffrées (« claims »), détection
d'incohérences (variance, revirements) et file de validation humaine.

## Stack

- **Backend** : FastAPI · SQLAlchemy async · SQLite (→ PostgreSQL/pgvector en prod)
- **Collecte X** : Nitter (RSS + HTML, rotation d'instances)
- **Collecte presse** : RSS + extraction (trafilatura)
- **LLM** : tier-1 open (Groq), tier-2 fidélité (Anthropic) — routage par tier
- **Embeddings** : Cohere (blocking sémantique des référents)
- **Frontend** : HTML + Tailwind + Chart.js (statique, servi par le backend — même origine)

## Démarrage (local)

### Backend

```bash
cd backend
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt   # (Linux/mac : .venv/bin/python)
cp .env.example .env                                       # renseigner les clés si besoin

# Construire et charger les jeux de données
.venv/Scripts/python -m src.scripts.build_pool
.venv/Scripts/python -m src.scripts.seed_pool
.venv/Scripts/python -m src.scripts.seed_media
.venv/Scripts/python -m src.scripts.seed_referentiel
.venv/Scripts/python -m src.scripts.seed_affiliations

# API + interface (collecte continue via scheduler intégré)
.venv/Scripts/python -m uvicorn src.app:app --port 8000
```

- Interface : http://localhost:8000/ (flux, Le Compteur, validation)
- Documentation API interactive : http://localhost:8000/docs

Le front est servi directement par le backend (`backend/static/`, même origine) :
pas de serveur séparé ni de CORS à configurer.

## Structure

```
backend/src/
  config.py · database.py · app.py · schemas.py · security.py · utils.py
  models/        Personality, Post, MediaSource, Article, Claim, Contradiction,
                 Theme/Subtheme/Referent, SpeakerAffiliation, CollectionRun
  services/
    collection/  nitter_client, x_collector, x_html_parser, press_collector,
                 relevance, extractor_client
    archive/     archiver (snapshot local + Wayback), archivebox_client
    analysis/    quantity, claim_extractor, claim_llm, contradiction_detector, embeddings
    scheduler.py
  routers/       health, personalities, posts, articles, referentiel, compteur, contradictions
  scripts/       build_pool, seed_*, backfill_x
  data/          pools + référentiel + lexiques (JSON)
  static/        front statique (flux, Le Compteur, validation) servi par FastAPI
infra/           docker-compose : Nitter self-host, ArchiveBox
```

## Configuration

Toutes les options passent par variables d'environnement (voir `backend/.env.example`).
Aucune clé n'est jamais committée. En production, renseigner au minimum
`DATABASE_URL`, `API_TOKEN`, `CORS_ORIGINS` et les clés LLM utilisées.

## Données

Personnalités et médias suivis : données publiques (élus, comptes officiels,
flux RSS de presse). Le périmètre « extrême droite » suit les usages de la
science politique et reste éditable (`backend/data/`, `aide/`).
