# Plan de la SUITE — phase ANALYSE — ED · MediaWatch

> Suite de `PLAN_COLLECTE.md` (collecte consolidée ✅). Cap : transformer le
> substrat propre en **corpus interrogeable + graphe de contradictions par
> référent** (north star ROADMAP). Méthodo détaillée dans `ANALYSE.md`.
> Garde-fous (non négociables) : précision > rappel, human-in-the-loop avant
> publication, fidélité au verbatim, méthode versionnée, RGPD (propos publics).

## État des lieux (réutilisable, déjà codé mais en sommeil)
- Modèles : `Claim`, `Contradiction`, `Referentiel`, `Taxonomy`.
- Services : `analysis/` (claim_extractor, claim_llm, claim_sources,
  contradiction_detector, embeddings, quantity), `classification/` (runner,
  theme_classifier — grille CAP déterministe + repli Cohere).
- API/Front : `/classification` `/compteur` `/contradictions` `/referentiel` ;
  `compteur.html`, `contradictions.html`.
- ⚠️ **LLM coupé** (`LLM_REFINE_ENABLED=false`) depuis le pivot « consolider la
  collecte ». Embeddings Cohere branchés mais **pas de pgvector réel**.
- ✅ Corpus désormais **nettoyé** (`text_clean`), métadonnées C0, porte C5.

---

## A-pré — Dette de déploiement à solder d'abord (côté user, rapide)
Avant d'analyser, le corpus prod doit être complet/propre :
1. `railway ssh` → `python -m src.scripts.seed_media` (charge les 32 nouvelles sources).
2. `python -m src.scripts.clean_articles` (re-nettoie le corpus existant).
3. Vérifier `EXTRACTOR_URL` + `SITE_COOKIES` (presse intégrale) ; `CEREBRAS_API_KEY`.
4. (option engagement) Nitter Railway + `sessions.jsonl` → `NITTER_SELF_HOSTED`.

---

## A0 — Socle analytique (prérequis de tout le reste)
1. **Postgres + pgvector réel** : colonne `vector` sur l'unité de claim (et/ou
   posts/articles), index ivfflat/hnsw. Débloque le **blocking sémantique** (A3).
2. **Alembic (baseline + stamp prod)** — enfin nécessaire : pgvector = changement
   NON additif. Procédure sûre déjà écrite dans `backend/MIGRATIONS.md`.
3. **Unité de claim** : segmenter post/article en **assertions atomiques** datées +
   attribuées (speaker, parti-à-la-date, source_url, reçu). Une ligne = un claim.
4. **Ré-activer le tier LLM** (`LLM_REFINE_ENABLED=true`, Cerebras `gpt-oss-120b`)
   sur le corpus **nettoyé** — l'extracteur déterministe seul est bruité.

**Acceptation A0** : pgvector opérationnel (insert + recherche cosine) ; Alembic
`current` aligné local/prod ; table de claims peuplée depuis posts+articles ;
LLM tier rallumé et testé sur échantillon réel.

## A1 — Classification thématique industrialisée (CamemBERT)
La grille CAP déterministe + Cohere existe ; on l'industrialise.
1. **Jeu étiqueté** : bootstrap (déterministe + LLM) → **échantillon validé humain**
   + accord inter-annotateurs (**Cohen's κ**, scripts réutilisables projet Paris).
2. **Fine-tune CamemBERT 2.0** (thème CAP + sous-thème) — réemploi du pipeline
   CamemBERT (projet Trend_Analysis Paris). Cohérent, reproductible, peu coûteux.
3. **Passe de masse** thème/sous-thème sur tout le corpus (posts ⊕ articles unifiés).
4. LLM en repli sur les cas à faible confiance uniquement.

**Acceptation A1** : classifieur évalué (held-out + κ ≥ seuil) ; corpus classé ;
distribution thématique cohérente vs grille.

## A2 — Le Grand Livre + Le Compteur (1re surface forte)
1. **Extraction de claims** : déterministe (quantité : valeur/unité/référent/
   horizon) + **LLM contraint par schéma** (canonicalisation, fidélité verbatim).
2. **Classification dans le référentiel FERMÉ** : on **range** dans `referent_key`,
   on ne les **génère pas** (fiabilité du Compteur).
3. **File de validation humaine** (déjà en place) : confirmer/écarter.
4. **Le Compteur** : nuage de points temporel par référent (réelles données) +
   reçus (snapshot/Wayback). Flux enrichi (badge « claim »).

**Acceptation A2** : claims canoniques validés ; Compteur affiche une série réelle
sourcée (ex. revirement RN retraite 60→62) ; provenance + reçu sur chaque point.

## A3 — Cohérence interne (détection d'incohérences)
1. **Stance / position** par référent (BERT fine-tuné ; LLM sur l'ambigu).
2. **Blocking sémantique** (pgvector A0) : comparer seulement les claims
   intra-référent proches → scalable.
3. **Contradictions** types 1 (revirement) / 2 (intra-parti) / 6 (variance) — le
   détecteur existe → le faire tourner sur le corpus réel ; type 3 (inter-partis).
4. **Graphe de contradictions** + cartes citables (reçus). Validation humaine.
5. **Évaluation** façon benchmark ICWSM 2025 (précision d'abord).

**Acceptation A3** : contradictions détectées + validées sur données réelles ;
graphe navigable ; faux positifs maîtrisés (seuils conservateurs).

## A4 — Surfaces produit & dataviz
1. **Le Compteur** (A2) abouti + **graphe de contradictions** (A3) navigable.
2. **Radar des réactions** à l'actualité ; **indice de cohérence** par figure/parti.
3. **Design** soigné (réf. `pbakaus/impeccable`, cf Note.md) ; exports citables.
4. **Carto** (extension) : couche CartoFaf StreetPress (acteurs/lieux par
   territoire, croisée à la PQR) — ⚠️ licence : lien/embed, pas de scrape de masse.

**Acceptation A4** : surfaces partageables, sourcées, validées humain.

## A5 — Extensions & rigueur
- **Type 4** (audit programme : référence 2022/2024 versionnée) ; **type 5**
  (fact-check externe INSEE/Eurostat).
- **Dérive de cadrage** (fighting words, distance de Wasserstein) — réemploi projet
  israélo-palestinien.
- **Symétrie de méthode** : ajout optionnel d'un **parti témoin** (le pipeline doit
  pouvoir tourner sur n'importe qui — déjà conçu pour).
- **Backfill X** (quand Nitter self-host) → profondeur temporelle du graphe.
- **API/exports** pour journalistes partenaires.

---

## Décisions à trancher (impactent A0-A1)
1. **Postgres/pgvector : maintenant ?** Recommandé — c'est le prérequis du blocking
   (A3) et l'occasion de poser Alembic proprement. (Sinon : embeddings en table
   simple + recherche brute le temps de valider, pgvector ensuite.)
2. **Budget d'annotation humaine** (A1/A3) : combien d'items annotés pour κ ? Plus
   d'annotation = classifieur plus fiable. Démarrage : ~300-500 items/tâche.
3. **Posture de publication** (spec §10) : interne asso / journalistes partenaires /
   public ? Conditionne le niveau de validation et les exports (A4).
4. **LLM providers** : Cerebras (open, rapide) pour le tier-1 de masse ; Anthropic
   réservé/économisé pour la canonicalisation fidèle (tier-2) ? À confirmer.

## Ordre d'exécution recommandé
**A-pré (déploiement)** → **A0 (pgvector + Alembic + claims + LLM on)** →
**A1 (CamemBERT thème)** ∥ **A2 (claims + Compteur)** → **A3 (contradictions)** →
**A4 (surfaces)** → **A5 (extensions)**.

A0 d'abord (tout en dépend). A1 et A2 parallélisables. A3 dépend de A0 (pgvector)
+ A2 (claims). Chaque couche est **rejouable** sur le verbatim stocké (jamais
re-collecter), **versionnée**, et **validée humain** avant toute publication.
