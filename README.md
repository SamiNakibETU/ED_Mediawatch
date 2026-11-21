# ED Mediawatch

Observatoire de Terra Nova Jeunes. Il lit les tweets d'un panel de figures du RN, de l'UDR et de
Reconquête, en tire des déclarations rangées sur un référentiel d'enjeux, puis repère les écarts :
dans le temps, par rapport au programme, entre membres d'un même parti. Aucun écart n'est publié
sans la décision d'un relecteur.

Les déclarations viennent des tweets seulement. La presse sert à la revue de la semaine.

## La chaîne

Tout se lance depuis `backend/`, dans l'ordre.

| Étape | Commande | Ce qu'elle fait |
|---|---|---|
| Collecter | lanceurs de `../donnees/` (voir plus bas) | écrit les tweets sur disque, hors du dépôt |
| Importer | `python -m src.scripts.importer_corpus` | fait entrer en base les tweets du disque (`--essai` compte sans écrire) |
| Lire | `python -m src.scripts.lire_registre --fournisseur openrouter` | filtre les tweets à enjeu, en extrait les déclarations (`--essai`, `--limit`) |
| Écarts | `python -m src.scripts.juger_ecarts --fournisseur openrouter` | détection, second avis, deux juges |
| Publier | `python -m src.scripts.publier_site` | ramène les décisions des relecteurs, exporte le site figé, l'envoie sur Cloudflare Pages |

Le fournisseur `codex` passe par l'abonnement ChatGPT (Codex CLI) quand son quota le permet.
Avant une passe complète : un essai court (`--limit 20`) et la mesure du coût.

## Où sont les choses

```
backend/
  src/
    models/      tables : posts, declarations, ecarts, engagements_programme, personalities...
    services/    collection/ (X, presse), analysis/ (registre, écarts, thèmes), archive/
    routers/     API FastAPI
    scripts/     les commandes de la chaîne, les diagnostics (diag_*), les chargements (seed_*)
    data/        panel, référentiel des enjeux, programme, jeux annotés
  static/        pages de la plateforme (enjeux, thèmes, écarts, revue, relecture)
  tests/
infra/
  pages/                  site figé et fonction des relecteurs (Cloudflare Pages)
  NITTER-LOCAL.md         Nitter local avec des comptes dédiés
  MISE-EN-SERVICE.md      déploiement sur un serveur à soi (non retenu pour la v1)
aide/                     listes de départ : médias, personnalités
docs/historique/          documents de conception de juin à août 2026, gardés pour mémoire
nitter/, scraper-service/ services de l'ancienne production Railway, à l'arrêt
```

Les données ne sont pas dans le dépôt. Elles vivent à côté, dans `../donnees/` :

| Dossier | Contenu | Lanceur |
|---|---|---|
| `x-comptes/` | collecte par les comptes de recherche, depuis juin 2026 | `lancer-collecte.cmd` |
| `x-timeline/` | pages de profil d'une instance Nitter | `lancer-collecte.cmd` |
| `x-historique/` | recherche datée par instance Nitter, 2022 à 2026 | `lancer-collecte.cmd` |
| `registre/` | journaux de lecture et des juges | `lancer-jour.cmd` : la passe complète du jour |
| `zeeschuimer/` | exports faits à la main dans le navigateur | |

La base de travail est `backend/ed_mediawatch.db` (SQLite). Une copie datée va dans `../donnees/`
avant toute passe qui l'écrit en masse.

## Installer

```bash
cd backend
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt
cp .env.example .env        # y poser les clés ; ce fichier n'est jamais commité
.venv/Scripts/python -m pytest
.venv/Scripts/python -m uvicorn src.app:app --port 8000   # plateforme locale : http://localhost:8000/
```

## Règles

- Aucun secret dans le dépôt : `.env`, `sessions.jsonl`, `nitter.conf`, cookies, clés.
- Collecte X : un seul flux de requêtes par instance, aucun défi anti-robot franchi. Les comptes X
  et leurs cookies ne sont manipulés que par leur titulaire.
- Rien de public sans relecture : le site reste fermé, un compte par relecteur.
- Un tweet cité dans un livrable se vérifie sur X ou sur Wayback.

Le plan de finalisation et l'état du chantier sont dans le dossier de l'étude, hors du dépôt
(`../documents/`, `../ETUDE.md`).
