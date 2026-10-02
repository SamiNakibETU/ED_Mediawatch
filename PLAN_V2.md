# ED Mediawatch V2 — plan et spécifications

Date : 2 octobre 2026. Référence : code à `main` (4 septembre), base de production
(≈ 11 400 déclarations, 113 comptes X, 57 flux presse), logs Railway du jour.

## 0. Diagnostic et décision

La collecte tient. L'analyse rend peu, et pas pour une raison de budget :

- 0 contradiction nouvelle par passe ; 14 paires jugées en août, 0 contradiction.
- 4 662 déclarations sur ≈ 6 000 sans sujet ; 384 sujets créés puis vidés à chaque passe.
- 0 déclaration rattachée à un référent sur la dernière passe (2 967 ambiguës, 2 033 sous le seuil).
- Chaîne de 17 étapes ; la moitié ne nourrit aucune surface lue.
- Pool : 132 RN + 16 UDR sur 168 comptes. Presque aucune sphère hors élus.
- Presse et X traités par la même chaîne : la presse n'a pas de locuteur certain,
  et a tiré la qualité de l'ensemble vers le bas.

Décision : deux produits distincts sur une base commune.

1. **Veille** — ce que disent les sphères de l'extrême droite, par thème, dans le temps.
   Sources X et presse. Peu de LLM.
2. **Positions** — ce que chaque acteur défend sur chaque enjeu, et comment ça
   bouge. Sources à locuteur certain uniquement : X, interviews, votes, programmes.
   La grille d'enjeux est construite par le système, pas écrite à la main.

Les deux partagent la collecte, le référentiel des acteurs et la base. Chaque
analyse est une couche recalculable ; on ne recollecte jamais.

## 1. Architecture générale

```
Sources ──▶ Collecte (mediascrapers) ──▶ Base ──▶ Enrichissement ──▶ Produits
  X                X syndication          posts       propositions       1. Veille
  presse           RSS + extraction       articles    sphères/thèmes     2. Positions
  YouTube [V2.1]   yt-dlp + Whisper        transcripts  enjeux/positions
  AN votes [V2.1]  open data               votes        séries temporelles
  programmes       PDF → texte             programmes
```

Modèles, par rôle :

| Rôle | Modèle | Pourquoi |
|---|---|---|
| Génération contrainte (découpe en propositions, nommage des enjeux, synthèses) | GPT Luna ou DeepSeek V4 Flash via OpenRouter | peu cher, sortie structurée |
| Décisions typées (pertinence, sphère, thème, rattachement, position) | Jev 1.13 via OpenRouter (`typesafe/jev-1.13`) | probabilités calibrées, pas d'hallucination de format, 0,042 $/M tokens entrée |
| Embeddings | local (sentence-transformers multilingue) ; Jina ou Cohere en option | gratuit, suffisant pour le blocking |
| Arbitrage hebdomadaire (revirements, faux positifs, synthèses éditoriales) | modèle frontière, batch | quelques dizaines de cas par semaine |

Règle : un modèle qui génère ne décide pas ; un modèle qui décide ne génère pas.

## 2. Référentiel des acteurs

### 2.1 Modèle `Actor` (remplace `Personality`)

| Champ | Type | Note |
|---|---|---|
| id | int | |
| full_name | str | |
| kind | enum | `person`, `party`, `media`, `collective` |
| x_handle | str, nullable, unique | |
| youtube_channel_id | str, nullable | V2.1 |
| an_id | str, nullable | identifiant Assemblée nationale |
| sphere_id | FK Sphere | obligatoire |
| sphere_rationale | text | une phrase sourcée justifiant le classement |
| sphere_source_url | str | |
| role | str | député, essayiste, influenceur, rédaction… |
| is_active | bool | |
| santé collecte | repris de Personality | last_status, consecutive_failures… |

### 2.2 Modèle `Sphere`

| Champ | Type |
|---|---|
| id | str (slug) |
| label | str |
| description | text |
| parent_id | nullable | hiérarchie à deux niveaux max |
| is_far_right | bool | faux pour les médias généralistes suivis en « reprise » |

Sphères initiales (à valider avec Terra Nova) :

```
rn_direction      Direction et porte-parole du RN
rn_elus           Élus RN (députés, sénateurs, eurodéputés, maires)
udr               UDR
reconquete        Reconquête et sa galaxie
souverainistes    Autres partis souverainistes (DLF, Patriotes…)
identitaires      Mouvance identitaire, catholiques traditionalistes
intellectuels     Essayistes, polémistes, revues
influenceurs      Créateurs de contenu, comptes à forte audience sans mandat
medias_mouvance   Frontières, Livre Noir, TV Libertés, Omerta, Boulevard Voltaire…
reprise           Médias généralistes suivis pour la reprise des thèmes (CNews, JDD, Europe 1) — is_far_right = false
```

### 2.3 `Affiliation` (existe : `party_of_record`)

Parti d'un acteur à une date. Conservé tel quel ; chaque proposition hérite du
parti valable à sa date.

### 2.4 Travaux

- Migration `Personality → Actor` avec `sphere_id` dérivé de `famille` ; les 7 comptes
  introuvables et les 3 homonymes identifiés le 26/08 sont retirés.
- Ajout cible : 30 à 50 acteurs hors élus (influenceurs, intellectuels, médias de
  la mouvance), chacun avec `sphere_rationale` et source.
- Pour le produit Positions, ajout de 20 à 30 comptes de contrôle (LR,
  Renaissance, gouvernement) marqués `sphere = reprise` ou sphère dédiée `controle`.
  Sans eux, aucune mesure de porosité n'est possible.

## 3. Collecte

Déjà en production ; extraite dans le paquet `mediascrapers` (repo séparé). ED
Mediawatch l'importe comme dépendance et garde la persistance.

| Source | Outil | Cadence | État |
|---|---|---|---|
| X timelines | `mediascrapers.x.SyndicationClient` | 4 h | en prod |
| X historique | `mediascrapers.x.Backfill` | à la demande | en prod |
| X tweets tronqués | `Backfill.expand_truncated` | après chaque passe | en prod |
| Presse | `mediascrapers.press.FeedCollector` | 4 h | en prod |
| YouTube | `yt-dlp` sous-titres auto ; Whisper si absents | quotidienne | V2.1 |
| Votes AN | open data `data.assemblee-nationale.fr` (scrutins, votes nominatifs) | hebdo | V2.1 |
| Programmes | PDF 2022, législatives 2024 ; 2027 à parution | une fois | V2.0 |

Spécification YouTube (V2.1) :

- `Channel` : `youtube_channel_id`, `kind` (`partisan` | `generaliste`), `actor_id` nullable.
- Découverte : flux RSS `youtube.com/feeds/videos.xml?channel_id=…`, pas d'API ni de quota.
- Filtre : titre ou description contient le nom d'un acteur actif → file de validation
  (1 clic) ; sinon ignoré. Les chaînes `partisan` passent sans validation.
- Texte : `yt-dlp --write-auto-sub --sub-lang fr --skip-download` ; si aucun sous-titre,
  audio → Whisper (API ou local). Stockage : `Transcript(video_id, text, segments[], method)`.
- Attribution : chaîne `partisan` → l'acteur de la chaîne ; chaîne `generaliste` →
  l'invité détecté dans le titre, segments non attribués marqués `speaker=unknown`.
  Diarisation (pyannote) hors périmètre tant que le besoin n'est pas démontré.

## 4. Couche 1 — Propositions

### 4.1 Objet `Proposition` (remplace `Claim` dans son rôle central)

Une proposition est une unité de sens autoportante, attribuée, datée.

| Champ | Type | Note |
|---|---|---|
| id | int | |
| source_kind | enum | `x`, `press_interview`, `transcript`, `program`, `vote` |
| source_id | int | FK polymorphe vers post / article / transcript / programme / scrutin |
| actor_id | FK Actor, nullable | **nul si locuteur incertain** ; alors exclu du produit Positions |
| party_at_date | str | hérité d'Affiliation |
| sphere_id | FK Sphere | hérité d'Actor |
| published_at | datetime | |
| verbatim | text | extrait exact de la source |
| canonical | text | reformulation autoportante, coréférences résolues, sans ajout |
| kind | enum | `position`, `fact_claim`, `attack`, `announcement`, `other` |
| is_political | float | probabilité Jev |
| theme | str | thème de niveau 1 (CAP major, déjà en place) |
| theme_p | float | probabilité Jev |
| embedding | vector | |
| dedup_key | str, unique | hash de (actor, canonical normalisé) |
| repeat_of | FK Proposition, nullable | redite : même acteur, même canonical, date postérieure |
| extraction_model | str | |
| created_at | datetime | |

### 4.2 Découpe (génération, LLM peu cher)

Entrée : un post X non-retweet, ou un paragraphe d'interview, ou un segment de
transcript. Sortie : JSON `[{verbatim, canonical}]`, schéma imposé.

Règles du prompt, invariantes :
- `verbatim` est une sous-chaîne exacte de l'entrée ;
- `canonical` ne contient aucune information absente de l'entrée ;
- un retweet n'est jamais découpé (mots d'un autre) ;
- un tweet `text_truncated` n'est jamais découpé avant expansion.

Contrôle : vérification programmatique que `verbatim in input` ; rejet sinon.

### 4.3 Décisions (Jev)

Un appel Jev par proposition, état = `canonical` + contexte minimal (acteur, parti,
date, texte source complet si ≤ 2 000 tokens). Questions :

```json
{
  "is_political": {"type": "noul", "instructions": "La proposition exprime-t-elle une position, une annonce, une accusation ou une affirmation sur un sujet de politique publique ou de vie politique ?"},
  "kind": {"type": "choice", "criteria": {"position": "…", "fact_claim": "…", "attack": "…", "announcement": "…", "other": "…"}},
  "theme": {"type": "choice", "criteria": { "<cap_major_code>": "<libellé + définition courte>", … }}
}
```

Seuils initiaux : `is_political ≥ 0,7` pour entrer dans les produits ;
`theme_p < 0,5` → thème `indetermine`, pas d'imputation forcée.

### 4.4 Coût

Découpe : ≈ 0,0035 $ par article mesuré en août ; un tweet ≈ 0,0005 $. Jev :
négligeable (< 0,00002 $ par proposition). Historique complet : < 10 $.

## 5. Couche 2 — Enjeux (grille auto-construite)

### 5.1 Objet `Issue`

| Champ | Type | Note |
|---|---|---|
| id | int | |
| question | text | formulée en question fermée neutre : « Faut-il maintenir l'aide militaire à l'Ukraine ? » |
| description | text | ce que recouvre l'enjeu, ce qu'il exclut |
| theme | str | CAP major |
| pole_for | text | ce que signifie « pour » |
| pole_against | text | ce que signifie « contre » |
| centroid | vector | |
| n_propositions | int | |
| first_seen / last_seen | datetime | |
| status | enum | `candidate`, `active`, `merged_into:<id>`, `retired` |
| created_by | enum | `clustering`, `human`, `program` |
| version | int | incrémenté à chaque reformulation |

### 5.2 Construction

Passe hebdomadaire :

1. Propositions `kind = position`, `is_political ≥ 0,7`, non rattachées.
2. Clustering sur embeddings (HDBSCAN, distance cosinus, taille min 5).
3. Pour chaque cluster nouveau : un appel LLM génère `question`, `description`,
   `pole_for`, `pole_against` à partir de 10 propositions représentatives. Statut `candidate`.
4. Fusion : si cosinus(centroid A, centroid B) > 0,92, un appel Jev `noul`
   « Ces deux questions désignent-elles le même enjeu ? » ; fusion si p > 0,85.
5. Passage `candidate → active` quand `n_propositions ≥ 10` et ≥ 3 acteurs distincts,
   ou validation humaine.

Amorçage : les mesures des programmes 2022 et 2024 sont découpées en propositions
(`source_kind = program`) et créent des enjeux `created_by = program`. La grille
part donc de ce que les partis ont écrit, et grandit avec ce qu'ils disent.

### 5.3 Rattachement d'une proposition à un enjeu

1. Présélection : 5 enjeux actifs les plus proches par embedding.
2. Jev, état = proposition + les 5 enjeux (question + description), question
   `choice` sur les 5 ids + option `aucun`.
3. Rattachement si p ≥ 0,75 ; `aucun` ou p faible → reste en attente du prochain clustering.

Stockage : table `PropositionIssue(proposition_id, issue_id, p, issue_version, model, created_at)`.
Une proposition peut tenir sur deux enjeux (p ≥ 0,75 sur chacun).

### 5.4 Recalcul

Toute reformulation d'un enjeu (version +1) invalide ses rattachements et positions,
recalculés à la passe suivante. Coût Jev d'un recalcul complet : < 1 $.

## 6. Couche 3 — Positions

### 6.1 Objet `Stance`

| Champ | Type | Note |
|---|---|---|
| proposition_id, issue_id | FK | |
| direction | enum | `for`, `against`, `conditional`, `evasive`, `off_topic` |
| direction_p | json | probabilité par option |
| intensity | float | 0 à 1, score Jev |
| condition | text, nullable | si `conditional` : la condition, extraite par LLM peu cher |
| model, issue_version, created_at | | |

### 6.2 Décision (Jev)

État : `canonical`, `verbatim`, acteur, parti, date, enjeu (question, description,
pole_for, pole_against), **position de référence du parti** sur cet enjeu si connue
(issue des programmes). Questions :

```json
{
  "direction": {"type": "choice", "criteria": {
    "for": "Soutient le pôle « pour » tel que défini",
    "against": "Soutient le pôle « contre »",
    "conditional": "Soutient un pôle sous condition explicite",
    "evasive": "Évoque l'enjeu sans se positionner",
    "off_topic": "Ne porte pas sur cet enjeu"}},
  "intensity": {"type": "score", "criteria": ["Mention incidente", "Position claire", "Position centrale, formulée comme engagement"]},
  "matches_party_line": {"type": "noul", "instructions": "La position est-elle conforme à la position de référence du parti fournie dans l'état ?"}
}
```

Validation humaine : `direction_p max` entre 0,5 et 0,8 → file de revue.
En dessous de 0,5 → `evasive` forcé, hors séries.

### 6.3 Position de référence

`IssueReference(issue_id, party, direction, source_url, valid_from, valid_to)`,
remplie depuis les programmes découpés, éditable à la main. C'est la seule partie
de la grille écrite par des humains, et elle est sourcée ligne à ligne.

## 7. Couche 4 — Séries et incohérences

### 7.1 Séries

Vue matérialisée `StanceSeries(actor_id, issue_id, week, direction_mode, mean_signed, n)`,
avec `signed = +intensity` pour `for`, `−intensity` pour `against`, 0 sinon.
Agrégations dérivées : par parti, par sphère, par semaine, mois, trimestre.

### 7.2 Détecteurs (déterministes, gratuits)

| Code | Détecte | Condition |
|---|---|---|
| D1 revirement intra-acteur | changement de direction dans le temps | deux fenêtres de 4 semaines, `mean_signed` de signe opposé, n ≥ 2 de chaque côté |
| D2 écart au programme | acteur vs référence du parti | `matches_party_line < 0,3` sur ≥ 2 propositions |
| D3 désaccord interne | deux acteurs du même parti | directions opposées sur 4 semaines, n ≥ 2 chacun |
| D4 dire / voter | position vs scrutin AN | V2.1 : stance `for` et vote `contre` (ou inverse) sur un scrutin rattaché à l'enjeu |
| D5 double registre | même acteur, canal partisan vs généraliste | V2.1 : directions ou intensités divergentes selon `source_kind` / `channel.kind` |

Chaque détection crée un `Finding(code, actor_id, issue_id, evidence[], status=pending)`.

### 7.3 Arbitrage (modèle frontière, hebdo)

Pour chaque `Finding` pending : état = les propositions preuves (verbatim, date,
source archivée), l'enjeu, la référence. Sortie structurée :

```
verdict: revirement_cache | evolution_assumee | perimetre_different | faux_positif
motif: texte neutre, 2 phrases max, cite les dates
```

Un `revirement_cache` passe en file de validation humaine avant publication.
Rien n'est publié sans validation.

## 8. Produit 1 — Veille

Surfaces :

- **Par sphère** : parts de thèmes (CAP) sur 7 / 30 / 90 jours, variation, 10 propositions les plus relayées.
- **Thèmes montants** : log-likelihood de Dunning semaine vs 8 semaines précédentes, par sphère et global.
- **Diffusion** : pour un thème ou un enjeu, premier acteur, chronologie des reprises
  (graphe `amplification`, existant), passage dans `reprise`.
- **Acteurs** : fiche (sphère, parti du jour, thèmes, enjeux, série de positions).

Besoins LLM : nommage des thèmes montants et synthèse hebdomadaire par sphère
(≤ 15 appels par semaine). Tout le reste est du comptage.

## 9. Produit 2 — Positions

Surfaces :

- **Enjeu** : question, référence par parti, répartition des directions par parti et par sphère, courbe dans le temps, propositions sources.
- **Acteur × enjeu** : série de positions, preuves datées et archivées.
- **Incohérences** : findings validés, par type (D1–D5), avec motif et preuves.
- **Grille** : liste des enjeux actifs et candidats, outil de fusion / reformulation / validation.

## 10. Revue humaine

Une seule file, typée : `ReviewItem(kind, ref_id, p, created_at, decided_at, decision, reviewer)`.

| kind | Déclencheur | Décision |
|---|---|---|
| issue_candidate | nouvel enjeu après clustering | valider / fusionner / reformuler / rejeter |
| stance_uncertain | direction_p entre 0,5 et 0,8 | confirmer / corriger |
| finding | verdict `revirement_cache` | publier / rejeter |
| youtube_video | vidéo détectée sur chaîne généraliste | retenir / ignorer |

Chaque décision humaine est stockée et sert de jeu d'évaluation (§12).

## 11. Ce qu'on retire de la chaîne actuelle

Mis en veille (code conservé, étapes retirées du scheduler) : `build_subjects`,
`label_subjects`, `enrich_claims` (référents), `cap_coding` tel quel (remplacé par
la question `theme` de Jev), `judge` sur paires libres, `redites` (remplacé par
`repeat_of`), `pledges` (remplacé par `IssueReference` + D2), `relevance` presse.

Conservés : collecte, `party_of_record`, `amplification`, archivage, `llm_usage`
et garde-budget, `pipeline_run`.

## 12. Évaluation

Avant toute mise en production d'une couche, un jeu de référence annoté à la main :

| Couche | Jeu | Mesure | Seuil d'acceptation |
|---|---|---|---|
| Découpe | 100 posts, 30 paragraphes d'interview | rappel des positions, précision de `verbatim in input` | rappel ≥ 0,85 |
| Jev `is_political` / `theme` | 200 propositions | accord avec annotation, calibration (ECE) | accord ≥ 0,85, ECE ≤ 0,08 |
| Rattachement | 200 propositions × enjeux | précision / rappel | P ≥ 0,85, R ≥ 0,75 |
| Direction | 200 propositions | accord, kappa inter-annotateurs humain d'abord | accord ≥ 0,80 |
| Détecteurs | tous les findings d'un mois | part de `faux_positif` après arbitrage | ≤ 0,30 |

Le test de la semaine 1 (§13) porte spécifiquement sur le français : Jev n'a pas de
performance publiée en français. Si l'accord sur `direction` est < 0,70, repli sur un
LLM peu cher contraint par schéma pour la couche 3, Jev gardé pour `is_political`
et `theme` si ceux-ci tiennent.

## 13. Déroulé

| Semaine | Livrable | Critère de sortie |
|---|---|---|
| 1 | Test Jev en français : 200 propositions, 20 enjeux manuels, annotation humaine | décision d'architecture couche 3 |
| 1 | `mediascrapers` branché comme dépendance ; crédits OpenRouter rechargés | collecte inchangée, tests verts |
| 2 | `Sphere`, `Actor`, migration, pool élargi (+30 acteurs, +20 contrôle) | chaque acteur a une sphère sourcée |
| 2–3 | Couche 1 sur l'historique X (découpe + Jev) | ≥ 10 000 propositions, éval §12 passée |
| 3 | Produit Veille v1 (sphères, thèmes montants, diffusion) | démontrable à Terra Nova |
| 4 | Programmes 2022/2024 découpés ; `IssueReference` | grille amorcée (≈ 100–200 enjeux) |
| 4–5 | Couche 2 : clustering, nommage, rattachement | éval rattachement passée |
| 5–6 | Couche 3 : positions ; séries | éval direction passée |
| 6 | Détecteurs D1–D3, arbitrage hebdo, file de revue | premiers findings validés |
| 7 | Produit Positions v1 | démontrable |
| 8+ | V2.1 : YouTube, votes AN, D4–D5 | une source à la fois |

## 14. Coûts de fonctionnement (estimation)

| Poste | Mensuel |
|---|---|
| Hébergement Railway (existant) | inchangé |
| Découpe LLM (≈ 5 000 propos/mois) | 2–5 $ |
| Jev (toutes décisions, recalculs compris) | < 1 $ |
| Arbitrage frontière hebdo (≈ 50 findings × 4) | 2–4 $ |
| Nommage et synthèses | < 1 $ |
| Whisper (V2.1, si sous-titres absents, ≈ 20 h/mois) | ≈ 8 $ |
| Total | 5–10 $ ; ≈ 20 $ avec YouTube |

Garde-budget existant conservé (5 $/jour, 60 $/mois), à abaisser à 3 $/jour.

## 15. Décisions ouvertes

1. Périmètre des acteurs de contrôle (LR, Renaissance, gouvernement) : qui, combien.
2. Typologie des sphères : validation par Terra Nova, et règle d'arbitrage pour les
   cas limites (CNews : `reprise`, pas `medias_mouvance`).
3. Qui tient la file de revue, à quelle fréquence.
4. Publication : quelles surfaces sont publiques, lesquelles réservées.
5. Juridique : courts verbatims sourcés et archivés ; pas de republication d'articles.
