# Infra — services optionnels (Docker)

Deux services débloquent les capacités « lourdes ». Tout le reste tourne sans eux
(RSS X + presse + snapshot local fonctionnent en pur local).

## 1. Nitter auto-hébergé → engagement + backfill X
Les instances Nitter publiques servent le RSS mais **challengent le HTML des
profils** (donc pas d'engagement ni de pagination). Pour les obtenir, self-host :

```bash
# 1. Préparer nitter.conf + sessions.jsonl (comptes X jetables — cf zedeus/nitter)
# 2. Lancer
docker compose -f infra/docker-compose.nitter.yml up -d
# 3. Pointer le backend dessus
echo "NITTER_SELF_HOSTED=http://localhost:8082" >> backend/.env
```
Effets : la collecte live passe en **HTML avec engagement** (likes/RT/réponses/
citations) et le **backfill** devient opérationnel :
```bash
cd backend && .venv/Scripts/python -m src.scripts.backfill_x   # depuis 2026-05-01
```

## 2. ArchiveBox → reçus possédés de la presse (HTML/PDF/screenshot/WARC)
```bash
docker compose -f infra/docker-compose.archivebox.yml up -d     # UI: http://localhost:8001
```
Backend (`backend/.env`) :
```
ARCHIVE_BACKEND=archivebox
ARCHIVEBOX_DATA_DIR=./infra/archivebox_data
ARCHIVEBOX_BINARY=docker compose -f infra/docker-compose.archivebox.yml run --rm archivebox
```
Puis `POST /archive-press` produit des archives multi-format opposables (et pousse
aussi vers archive.org via `SAVE_ARCHIVE_DOT_ORG`).

> Sans Docker : `ARCHIVE_BACKEND=wayback` (snapshot HTML local + lien Wayback si
> capture existante) reste actif par défaut.
