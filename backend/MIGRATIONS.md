# Migrations de schéma — ED_Mediawatch

## État actuel : auto-migration additive (au boot)
`src/database.py::init_db()` fait, à chaque démarrage, sur SQLite **et** Postgres :
1. `Base.metadata.create_all` — crée les **tables** manquantes ;
2. `_autoadd_missing_columns` — `ALTER TABLE ADD COLUMN` pour les **colonnes**
   manquantes (nullable, chaque ALTER dans son SAVEPOINT).

C'est **suffisant et sûr pour tout changement ADDITIF** (nouvelles colonnes
nullable, nouvelles tables) — c'est le cas des champs **C0** (qualité d'extraction
sur `Article`, `views`/`content_hash`/`collected_via`/`lang` sur `Post`,
`published_estimated`). Vérifié : appliqué à une table pré-existante, il ajoute les
colonnes en préservant les lignes (nouvelles colonnes = NULL).

> Donc C0 se déploie **sans Alembic** : un simple redeploy applique le schéma.

## Limite : changements NON additifs
L'auto-migrate ne sait pas : renommer/supprimer une colonne, changer un type,
ajouter une contrainte NOT NULL/UNIQUE rétroactive, **backfiller des données**.
Le jour où on en a besoin (≥ P1), on introduit Alembic.

## Introduire Alembic SANS casser la prod (procédure)
La prod Postgres a déjà les tables → il ne faut **jamais** lancer un `upgrade` qui
recrée l'existant. Procédure de bascule :
1. `pip install alembic` ; `alembic init alembic` ; pointer `env.py` sur
   `Base.metadata` (async) et `DATABASE_URL`.
2. Générer une **révision baseline** qui décrit le schéma **courant**
   (`alembic revision --autogenerate -m "baseline"`), la relire.
3. **Stamper** chaque base existante à cette baseline **sans l'exécuter** :
   `alembic stamp head` (local ET prod via `railway run`). → Alembic considère le
   schéma courant comme déjà appliqué.
4. À partir de là : tout changement = nouvelle révision ; `alembic upgrade head`
   au déploiement. On **retire alors** `_autoadd_missing_columns` du boot (ou on
   le garde en filet le temps de la transition, les deux étant idempotents).

> Tant que l'étape 3 (stamp prod) n'est pas faite, NE PAS exécuter `alembic
> upgrade` sur la prod. Cette mise en place se fera quand on aura la main sur la
> prod pour stamper en sécurité (à planifier avec P1 / pgvector).

## 2026-08-26 — table `llm_usage_events` (comptabilité LLM)
Nouvelle table additive → couverte par l'auto-migration au boot (aucune action).
Budgets par env : `LLM_DAILY_BUDGET_USD` / `LLM_MONTHLY_BUDGET_USD` ; suivi via
`GET /llm/costs`.

## 2026-08-26 — colonnes de provenance sur `contradictions`
`detection_method` (défaut « deterministe ») et `judge_version` : ajouts de
colonnes nullable/à défaut → couverts par l'auto-migration au boot. Les arêtes
existantes restent « deterministe », ce qui est exact.

## 2026-08-26 — `posts.text_truncated` (syndication X coupe à 280)
Colonne booléenne additive → auto-migration au boot. Marquage rétroactif des
posts `synd` ≥ 265 caractères, puis `python -m src.scripts.enrich_x` (texte
intégral via fxtwitter, déclarations L0 du texte coupé invalidées).

## 2026-08-26 — profil X sur `personalities`
`x_user_id`, `followers_count`, `statuses_count`, `x_protected`,
`profile_refreshed_at` : additifs, remplis à chaque passe de syndication.

## 2026-08-28 — pgvector (production uniquement)
`vector_index.ensure_ready()` crée l'extension, la colonne `claims.embedding_vec`
et l'index HNSW — tout est ADDITIF et idempotent, donc conforme à la doctrine
« pas d'Alembic tant que c'est additif ». La colonne JSON `embedding` reste la
source de vérité ; le vecteur en est une projection, resynchronisable.
Exécuté par l'étape de pipeline `vector_index`. Sans effet sur SQLite.
