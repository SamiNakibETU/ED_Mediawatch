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
