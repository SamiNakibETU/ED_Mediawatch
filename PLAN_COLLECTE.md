# Plan de fiabilisation de la COLLECTE — ED · MediaWatch

> Objectif : **collecter tout, par tous les canaux, avec des métadonnées
> parfaites et archivées**, prêt à passer à l'analyse. Principe directeur
> (ROADMAP §1) : _ce qu'on ne collecte pas est perdu ; ce qu'on raffine est
> rejouable_ → l'ingestion + l'archivage doivent être **irréprochables** ; le
> reste s'affine.

Statut au 2026-06-28 : v1 déployé Railway (Postgres). Collecte X (RSS) + presse
(28 sources) live ; archivage et engagement **construits mais non branchés**.

## Décisions actées (2026-06-28)
- **Engagement X** : tester la capacité **HTML** des instances Nitter publiques
  actuelles ; basculer le live sur HTML si elles servent la timeline. **Self-host
  Nitter en fallback** si le HTML public est challengé.
- **Anti-paywall presse** : Jina + Wayback (déjà actifs) **+ déployer ladder
  (Railway) + cookies d'abonné** (`SITE_COOKIES`) pour les paywalls durs.
- **Couverture presse** : **spectre complet + PQR (60-85 titres)** du CSV
  `aide/medias_francais.csv` (axe territorial exploitable).

## Réemploi prioritaire — branche `v2/media-watch` (directive user)
On **s'inspire totalement** du dépôt `breve_de_presse_PMO@v2/media-watch`, dont les
briques productionnées sont à adopter telles quelles :
- **`scraper-service/`** — microservice FastAPI anti-paywall (curl_cffi TLS-impersonation,
  Playwright stealth, Scrapling/Cloudflare, googlebot_referer, archive.ph, Jina,
  Wayback, LLM cleanup), scoring de complétude, endpoints `/extract` `/extract/batch`
  `/verify` `/stats`, Dockerfile + railway.toml prêts. → **cœur du canal presse** (C2.3).
  Le contrat `/extract` colle déjà à `extractor_client._via_service`.
- **`archivebox_client`** (reçus multi-format possédés) — déjà repris dans
  `services/archive/`, à activer en self-host plus tard (C3).
- **`scraper_monitor` router** (`/stats`, taux de succès par stratégie) — à reprendre
  pour l'observabilité (C4).
- Patterns de déploiement Railway multi-service (`railway.json`, `deploy-railway.ps1`,
  `docker-entrypoint.sh`, smoke tests prod).

> La branche est récupérée en local : `_reference/breve_de_presse_PMO` réf
> `v2/media-watch` (`git show v2/media-watch:scraper-service/...`).

---

## C0 — Métadonnées parfaites (socle data) — _prérequis de tout_

Tout l'analytique (claims, contradictions, compteur) dépend de la qualité et de
la complétude des champs. On fige le schéma cible **maintenant**.

### C0.1 Modèle `Post` (X)
Ajouter (additif, nullable — sûr sur Postgres via auto-migrate) :
- `views` (impressions) — `Integer | None`.
- `lang` — `String(8)` (détection langue, défaut `fr`).
- `content_hash` — `String(64)` : hash du texte normalisé → détecter
  reposts/éditions, dédup sémantique au-delà du `guid`.
- `collected_via` — `String(8)` : `rss` | `html` (traçe la complétude des métas).
- `quoted_url` / `reply_to` — contexte conversationnel (optionnel, utile stance).

### C0.2 Modèle `Article` (presse) — **le plus important**
Aujourd'hui impossible de savoir si `content` est l'article **intégral** ou un
**chapô tronqué** → bloquant pour l'analyse. Ajouter :
- `extraction_method` — `String(24)` : valeur **rendue par le scraper-service v2**
  (`curl_cffi` | `playwright_stealth` | `googlebot_referer` | `archive_ph` |
  `jina_ai` | `wayback` | `llm_cleanup` | `scrapling_cf`) ou local (`rss_full` |
  `cookies` | `summary`).
- `is_full_text` — `Boolean` : mappé sur `is_complete` du scraper-service (scoring
  de complétude) ; à défaut, extrait propre ≥ seuil et non paywall.
- `paywalled` — `Boolean` : marqueur de mur payant détecté.
- `confidence_score` — `Float | None` : rendu par le service (qualité d'extraction).
- `lang` — `String(8)`.
- `section` / `rubrique` — `String(80)` si le flux la fournit.

### C0.3 Propagation
- **Source de vérité = le scraper-service v2** : son `/extract` retourne déjà
  `extraction_method`, `is_complete`, `word_count`, `confidence_score`,
  `all_attempts`. `extractor_client._via_service`
  ([extractor_client.py:30](backend/src/services/collection/extractor_client.py#L30))
  ne lit aujourd'hui que `content` → **enrichir** pour remonter tous ces champs.
- `extract_fulltext()` renvoie un dataclass `Extraction(text, method, is_full,
  paywalled, confidence)` au lieu d'un `str` ; `press_collector._resolve_body`
  les écrit sur `Article`.
- `published_at` **jamais NULL** : fallback sur l'heure de fetch, **flaggé**
  (`published_estimated: Boolean`) pour ne pas polluer l'axe temporel.

### C0.4 Migrations — introduire **Alembic** (baseline)
L'auto-migrate ([database.py:65](backend/src/database.py#L65)) est purement
additif : incapable de backfiller/retyper. Poser une **baseline Alembic** sur le
schéma courant + 1ʳᵉ révision pour C0. Garder l'auto-add comme filet (idempotent),
mais toute évolution **données** passe par Alembic. (ROADMAP §6 le réclame.)

**Acceptation C0** : un script `diag_metadata` montre, par canal, le taux de
remplissage de chaque champ + distribution `extraction_method` ; 0 `published_at`
NULL ; schéma identique local/prod (vérifié via Alembic `current`).

---

## C1 — Canal X complet (engagement + date exacte + couverture pool)

### C1.1 Activer l'engagement sur le live
- **Sonde HTML** : étendre `NitterClient` d'un test `can_serve_html(instance)`
  (déjà semi-présent via `_looks_like_timeline`). Au boot, classer les instances
  qui servent réellement la timeline HTML.
- `run_collection` ([x_collector.py:206](backend/src/services/collection/x_collector.py#L206)) :
  `use_html = self_hosted OR (au moins une instance publique sert le HTML)` —
  ne plus dépendre **uniquement** de `nitter_self_hosted`.
- Si HTML public KO → **self-host Nitter** (service Railway, compte guest/auth),
  `NITTER_SELF_HOSTED` → bascule sans changer le code.
- ⚠️ **`views`** : Nitter **n'expose pas** le compteur de vues X dans la plupart
  des cas → le documenter ; si introuvable via Nitter, `views` reste NULL (ne pas
  prétendre l'avoir). Likes/RT/réponses/citations + **date exacte (heure:min)**,
  eux, sont fournis par le HTML ([x_html_parser.py:48-78](backend/src/services/collection/x_html_parser.py#L48)).

### C1.2 Re-poll d'engagement (cible mouvante)
- Nouveau job scheduler : re-fetcher en HTML les posts des **dernières 72h** pour
  rafraîchir `likes/retweets/...` + `engagement_captured_at`. Idempotent (UPDATE
  par `guid`). Cadence ~12h.

### C1.3 Backfill mai 2026 (cold start, résumable)
- Lancer `run_backfill(since=2026-05-01)` ([x_collector.py:167](backend/src/services/collection/x_collector.py#L167))
  une fois le HTML confirmé. One-shot via `railway ssh`, reprenable (dédup guid).

### C1.4 Couverture du pool
- **55/168 personnalités sans handle** : script de complétion/vérif des handles
  manquants + revue des `verif=a_confirmer` (un mauvais @ pollue plus qu'un vide).
- Cible : maximiser `with_handle` parmi les figures actives prioritaires.

**Acceptation C1** : ≥1 instance HTML opérationnelle ; posts récents portent
likes/RT/date précise ; backfill mai→présent terminé ; rapport de couverture pool
(handles actifs / collectés / muets).

---

## C2 — Canal Presse complet (couverture spectre + PQR + qualité)

### C2.1 Découverte & validation RSS des 85 titres
- Script `discover_rss` : pour chaque titre du CSV, tenter les patterns RSS
  usuels (`/rss`, `/feed`, `/rss.xml`, sitemap), **valider** (HTTP 200 + parse +
  entrées datées récentes), écrire dans `media_sources_fr.json` avec `leaning`/
  `category` du CSV. Marquer morts (ex. Frontières DNS) `is_active=false` + note.
- Cible 60-85 sources actives, dont **PQR complète** (territorial) et **médias ED**
  (TV Libertés, Livre Noir, Omerta, Boulevard Voltaire…).

### C2.2 Qualité d'extraction (dépend de C0.3)
- Brancher `extraction_method` / `is_full_text` / `paywalled` sur chaque article.
- Le seuil `_RSS_FULLTEXT_MIN=1200` ([press_collector.py:53](backend/src/services/collection/press_collector.py#L53))
  reste, mais on **enregistre** désormais pourquoi un texte est jugé complet/tronqué.

### C2.3 Anti-paywall — **adopter le `scraper-service` v2/media-watch** (centre de gravité)
Le microservice `scraper-service/` de la branche `v2/media-watch` est la version
productionnée de la cascade — bien supérieure à l'extracteur in-process actuel.
Son `/extract` correspond **déjà** au contrat appelé par `_via_service`.
- **Copier `scraper-service/`** dans ED_Mediawatch (ou repo/déploiement Railway
  jumeau) ; déployer comme **service Railway séparé** (Dockerfile fourni :
  Playwright + curl_cffi, `--workers 1` pour éviter l'OOM Chromium).
- Sur le backend : poser **`EXTRACTOR_URL`** = URL du service → la presse route
  par lui en tête de cascade, code presse inchangé.
- **Adapter les overrides domaine au paysage FR** (`ultimate_extractor._get_strategies_for_url`) :
  `lemonde.fr`/`lefigaro.fr` déjà présents → ajouter `liberation.fr`, `mediapart.fr`,
  `lepoint.fr`, `lexpress.fr`, `letelegramme.fr`, groupe **EBRA** (PQR : ledauphine,
  estrepublicain, dna…), avec `googlebot_referer` + `archive_ph` en tête (gratuits,
  efficaces mi-2026 sur la presse FR).
- **LLM cleanup** : le tier T6 utilise Groq par défaut — or **le compte Groq est
  bloqué** (cf mémoire data-sources). Repointer `SCRAPER_LLM_CLEANUP_BASE_URL`/
  `MODEL` sur **Cerebras** (`gpt-oss-120b`, OpenAI-compatible) ou désactiver.
- **`SITE_COOKIES`** (secret env, backend) reste le tier le plus fiable pour les
  paywalls **durs souscrits** (Le Monde…), en amont du service.
- ladder/Jina/Wayback : déjà couverts par le service (jina_ai, wayback) — `LADDER_URL`
  devient **optionnel** (repli) plutôt que pièce maîtresse.
- Vérifier sur échantillon réel (Le Monde/Libé/Figaro/Télégramme) via `/verify`.

### C2.4 Robustesse flux
- `feed.entries[:60]` ([press_collector.py:146](backend/src/services/collection/press_collector.py#L146)) :
  pour les sources à fort débit, augmenter/paginer pour ne rien perdre entre 2 passes.
- `published_at` fallback + flag (cf C0.3).

**Acceptation C2** : 60-85 sources actives validées ; **scraper-service v2 déployé
sur Railway**, `EXTRACTOR_URL` posé, `/health` vert ; distribution
`extraction_method` saine (part de `is_full_text=True` élevée hors paywalls durs) ;
échantillon paywall dur (Le Monde/Libé/Figaro) récupéré intégral.

---

## C3 — Archivage / reçus (brancher l'existant) — **priorité ROADMAP P0.5#1**

`run_archival` ([archiver.py:60](backend/src/services/archive/archiver.py#L60))
n'est **appelé par rien**. Tweet supprimé / article paywallé = perdu aujourd'hui.

### C3.1 Brancher au scheduler
- Jobs `archive_press` + `archive_x`, résumables (n'archivent que `archived_at IS
  NULL`), rate-limités (Wayback lent). Cadence alignée sur la collecte.

### C3.2 Wayback **push** (pas seulement pull)
- Actuellement on ne fait que `availability` (capture **existante**). Pour les
  items frais (surtout X), **déclencher Save Page Now** pour *créer* le reçu.
  Sinon un tweet récent n'a aucune archive.

### C3.3 ⚠️ Filesystem Railway éphémère
- `data/snapshots/*.html` ([archiver.py:38](backend/src/services/archive/archiver.py#L38))
  est **perdu à chaque redeploy** (FS éphémère). Les reçus locaux doivent aller
  vers un **stockage durable** : Wayback push (URL pérenne) + option HTML brut en
  Postgres (`Article.raw_html`) ou volume/objet. **À trancher** : volume Railway
  vs colonne DB vs bucket.

**Acceptation C3** : chaque nouvel item obtient `snapshot_url` (Wayback) sous N
heures ; taux d'archivage suivi ; reçus survivent à un redeploy.

---

## C4 — Fiabilité & observabilité (« organisé, bien fait »)

### C4.1 Suivi par source/handle (pas seulement agrégé)
- Table fille `SourceRunResult(run_id, source/handle, status, new, error)` OU
  champs JSON sur `CollectionRun`. Rend visible un handle/source **muet récurrent**
  (instance qui bloque, flux cassé) — au-delà du compteur `errors`.

### C4.2 Alerting fraîcheur
- `/health/freshness` ([health.py:52](backend/src/routers/health.py#L52)) existe
  mais doit être **poll é**. Ajouter un cron (ScheduleWakeup/cron Railway) ou une
  notification quand `stale`/`zombie_runs` > 0.

### C4.3 Résilience
- Backoff/retry par source ; `max_instances=1 + coalesce` déjà OK ; vérifier qu'un
  job long ne chevauche pas le suivant.

### C4.4 Tests
- Tests des nouveaux champs métas + qualité d'extraction (fixtures HTML/RSS réels),
  du fallback `published_at`, du parsing engagement compact (`1.2K`).

**Acceptation C4** : un handle/source en panne est visible en < 1 passe ; alerte
automatique sur collecte muette ; suite de tests verte.

---

## C5 — Porte « prêt pour l'analyse » (definition of done)

Endpoint + script `collection_report` agrégeant, par canal :
- **Couverture** : % pool avec handle actif collecté ; nb sources actives / mortes.
- **Complétude métas** : % posts avec engagement+date précise ; % articles
  `is_full_text`.
- **Archivage** : % items avec reçu (snapshot_url).
- **Fraîcheur** : âge de la dernière passe par canal/source.

On ne « passe à l'analyse » que quand ce rapport est au vert sur seuils définis.

---

## Ordre d'exécution recommandé
**C0 (schéma+Alembic)** → **C3 (archivage : ne plus rien perdre)** en parallèle de
**C1 (engagement X)** et **C2 (presse)** → **C4 (observabilité)** → **C5 (gate)**.

C0 et C3 d'abord car ils touchent au principe « ne rien perdre » et conditionnent
la qualité de tout le reste. C1/C2 sont les deux canaux. C4/C5 verrouillent.
