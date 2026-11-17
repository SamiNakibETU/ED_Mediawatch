# Image du backend ED Mediawatch (API FastAPI + pages statiques + collecte planifiée).
# Le schéma se crée et se complète au démarrage (src/database.py::init_db) : pas de migration à lancer.
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app

# lxml et asyncpg ont des roues binaires ; libxml2 reste utile à trafilatura
RUN apt-get update && apt-get install -y --no-install-recommends libxml2 libxslt1.1 curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY src ./src
COPY static ./static
COPY data ./data

EXPOSE 8000
HEALTHCHECK --interval=60s --timeout=10s --retries=3 CMD curl -fsS http://localhost:8000/health/freshness || exit 1
CMD ["uvicorn", "src.app:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
