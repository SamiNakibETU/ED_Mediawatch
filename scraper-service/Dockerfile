# Service de Scraping Avancé - L'Orient-Le Jour
# Architecture optimisée pour contourner les paywalls et extraire 100% du contenu

FROM python:3.11-slim-bookworm

# Dépendances système pour Playwright, curl et extraction de texte
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    wget \
    gnupg \
    ca-certificates \
    pkg-config \
    build-essential \
    libicu-dev \
    icu-devtools \
    fonts-liberation \
    libasound2 \
    libatk-bridge2.0-0 \
    libatk1.0-0 \
    libc6 \
    libcairo2 \
    libcups2 \
    libdbus-1-3 \
    libexpat1 \
    libfontconfig1 \
    libgbm1 \
    libgcc1 \
    libglib2.0-0 \
    libgtk-3-0 \
    libnspr4 \
    libnss3 \
    libpango-1.0-0 \
    libpangocairo-1.0-0 \
    libstdc++6 \
    libx11-6 \
    libx11-xcb1 \
    libxcb1 \
    libxcomposite1 \
    libxcursor1 \
    libxdamage1 \
    libxext6 \
    libxfixes3 \
    libxi6 \
    libxrandr2 \
    libxrender1 \
    libxss1 \
    libxtst6 \
    lsb-release \
    xdg-utils \
    libxml2 \
    libxslt1.1 \
    && rm -rf /var/lib/apt/lists/*

# Installation des dépendances Python
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Installation des browsers Playwright
RUN playwright install chromium
RUN playwright install-deps chromium

# Copie du code
COPY src/ ./src/
COPY config/ ./config/

# Variables d'environnement pour anti-détection
ENV PYTHONUNBUFFERED=1
ENV PLAYWRIGHT_BROWSERS_PATH=/root/.cache/ms-playwright
ENV DISPLAY=:99

# Health check (utilise le PORT Railway si présent, sinon 8000)
HEALTHCHECK --interval=30s --timeout=10s --start-period=120s --retries=3 \
    CMD python -c "import os, httpx; httpx.get(f'http://localhost:{os.getenv(\"PORT\", \"8000\")}/health', timeout=5)" || exit 1

EXPOSE 8000

# Railway injecte $PORT — on l'utilise via expansion shell.
# Un seul worker pour éviter de charger 2 Chromium en parallèle (OOM sur Railway).
ENTRYPOINT []
CMD ["/bin/sh", "-c", "exec uvicorn src.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1 --timeout-keep-alive 30"]
