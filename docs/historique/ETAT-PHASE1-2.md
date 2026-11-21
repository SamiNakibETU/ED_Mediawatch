# ED Mediawatch — état après phases 1 et 2 (26 août 2026)

Validé sur corpus réel : 85 articles collectés (57 sources), 488 déclarations
extraites, coût total **0,172 $**. 134 tests verts.

## Ce qui marche de bout en bout
- Collecte presse (RSS + texte intégral) → L0 (segmentation LLM) → embeddings →
  rattachement au référent → détection déterministe → juge sémantique.
- Juge validé : un revirement formulé sans chiffres ni stance explicite
  (« maintenir l'aide à l'Ukraine » vs « cesser toute livraison ») est détecté,
  typé « revirement intra-locuteur », motif neutre et exact.
- Garde-fous du juge vérifiés en réel : périmètres différents → `compatible`,
  changement assumé → `evolution_assumee`, sujets disjoints → `hors_sujet`.

## Corrections majeures apportées (bugs de fond, pas de confort)
1. **Attribution presse** — le L0 imputait TOUT un article à la seule figure
   mentionnée : propos de Marylise Léon et Benjamin Haddad prêtés à Marine Le Pen,
   puis « contradictions » bâties dessus. Un article n'est plus jamais réputé
   être la parole d'une personne (`speaker = None`).
2. **Faux positifs d'identité** — 47 des 85 articles étaient mal attribués
   (« parc Dragon Ball » → Nicolas Dragon, « cinéma bourgeois » → Le Bourgeois,
   « Renaud Girard » → Christian Girard). Trois gardes : capitalisation d'origine,
   prénom d'homonyme, nom propre composé. Plus déduplication des motifs inclus
   (« le pen » + « marine le pen » = un locuteur).
3. **Unités incompatibles** — « déficit pluviométrique de 70 % » héritait de
   l'unité `pct_pib` et devenait comparable au déficit public. Exclusions
   contextuelles par référent (`exclude` dans referent_triggers.json).
4. **Dépendance bloquante Cohere** — sans clé, aucun embedding, donc aucune
   contradiction possible. Repli local (sentence-transformers, MiniLM
   multilingue, CPU, gratuit) avec seuil calibré par backend : les espaces
   vectoriels ne sont pas comparables (Cohere 0,50 / local 0,42, mesuré).
5. **Comptabilité LLM** — tokens réels du provider, grille de prix, budget armé
   (5 $/j, 60 $/mois) couvrant TOUS les chemins d'appel, `BudgetExceeded` attrapé
   pour un arrêt propre. `GET /llm/costs`.

## Coûts mesurés
| Étape | Appels | Coût |
|---|---|---|
| L0 segmentation (48 articles) | 48 | 0,163 $ |
| Juge sémantique | 1 | 0,0002 $ |
| Gate tier-1 + refine | 43 | 0,009 $ |

Soit **~0,0035 $ par article** segmenté. La sortie coûte plus cher que l'entrée
(121k tokens out vs 86k in) : le levier de coût est le pré-filtre, pas le modèle.

## Collecte X : résolue sans Nitter (26/08, soir)
Nitter est mort (mise en demeure X Corp du 24/08). Trois voies gratuites, sans
compte ni proxy, vérifiées en réel :
- **Syndication officielle** (`syndication.twitter.com/srv/timeline-profile`,
  l'endpoint des widgets embarqués) : ~20-100 tweets complets par handle avec
  engagement et quote/RT. **1 623 tweets sur 113 handles en une passe.** Quota
  annoncé par le serveur (30 req / 15 min, en-têtes `x-rate-limit-*`) : le
  client le lit et dort jusqu'au reset — passe complète ≈ 1 h, dans le pas de
  4 h du scheduler. `services/collection/x_syndication.py` (voie primaire).
- **Backfill historique** : Wayback CDX → identifiants, fxtwitter → contenu.
  `python -m src.scripts.backfill_x 2022 [handles]`. Testé : 5/6 tweets MLP.
- Nitter reste en repli de code, inactif.

## Ancien bloquant (avant résolution)
Aucune instance Nitter accessible depuis cette IP (`probe_nitter` : 0/9). Sans
posts X, aucune déclaration n'a de locuteur certain, donc le juge n'a aucune
paire à examiner sur le corpus presse — c'est le comportement correct, pas un
bug. Options : self-host Nitter (`infra/docker-compose.nitter.yml`), IP
résidentielle, ou sources à attribution certaine (INA, JO, CR Assemblée) —
juridiquement plus propres, cf. l'arbitrage à prendre avec Terra Nova.

## Reste à faire
- Trancher l'arbitrage collecte X (ToS/réputation) avant toute publication.
- Annoter ~200 déclarations pour mesurer précision/rappel du L0
  (`python -m src.scripts.eval_l0 export` puis `score`).
- Phase 3 : timeline par personnalité × thème, fiches drift, revue éditable.

## Analyse — ajustements sur corpus X réel (26/08, soir)
- **Blocking du juge élargi** : sur corpus réel, ~90 % des déclarations
  n'atteignent aucun des 28 référents (grille fine, discours large). Le juge
  bloque désormais par référent OU par (locuteur, thème). Première passe sur
  ~100 déclarations X d'un mois : 14 paires, 12 `compatible`, 2 `hors_sujet`,
  0 contradiction — sobriété voulue ; les revirements exigent de la profondeur
  (→ backfill 2023+ lancé sur MLP, Bardella, Zemmour, Chenu, Knafo).
- **Passe normative déterministe gardée** : une opposition n'est imputable
  qu'entre locuteurs connus (même règle que le juge). 4 arêtes fausses issues
  de presse non attribuée purgées.

## Leçons du code Nitter portées (26/08, nuit)
Lecture de `zedeus/nitter` (consts/api/apiutils/parser) : TOUT y passe par des
sessions de compte (GraphQL + x-client-transaction-id) — rien d'anonyme. Ça
confirme la voie syndication comme seule porte sans compte. Portés chez nous :
- **Troncature à 280** : la syndication n'expose pas `note_tweet` (Nitter le lit
  en GraphQL). Vérifié : 304 car. vs 501 chez fxtwitter. → `text_truncated`
  (indice `display_text_range` ≥ 270), `x_enrich` récupère le texte intégral
  par ID et **invalide les déclarations L0 tirées du texte coupé**. 722 posts
  concernés sur 2 155 au premier marquage.
- `display_text_range` appliqué en points de code (retire @mentions de tête et
  lien média de queue) ; vidéos → meilleure variante mp4 (pour l'ASR à venir).
- Robustesse `apiutils.nim` : 404 à corps vide = transitoire (retry), page
  Cloudflare = blocage (retry), quota lu dans `x-rate-limit-*`.
- Timeline vide ≠ ok : statut `empty` dans la santé par handle (protégé,
  suspendu, muet). Profil X persisté (id stable, followers) à coût nul.
- **L0 et troncature** : l'extracteur ignore désormais tout post `text_truncated`
  (LLM jamais dépensé sur un texte coupé ; `enrich_x` d'abord). Backfill CDX
  découpé par préfixe d'identifiant (tranche temporelle) et double domaine
  `x.com`/`twitter.com` : les gros comptes (Zemmour 504 en une requête) passent
  en 5 requêtes de 2-20 s.
- **Mesure de la troncature** (26/08, 17 h) : 770 tweets suspects, **201 réellement
  tronqués (26 %)**, 164 déclarations L0 invalidées et refaites sur le texte
  entier. Sans cette passe, un quart des longues prises de position auraient été
  analysées amputées.
- **Bug corrigé** : lots d'INSERT hétérogènes (`quoted_*` absents sur les tweets
  sans citation) faisaient échouer tout le lot d'un handle — 15 handles
  orphelins après la passe complète, recollectés.

## Qualité du pool (26/08, 17 h 30) — action Sami
`python -m src.scripts.diag_handles` sur les 11 handles muets : **7 introuvables**
(renommés/suspendus : nadinelechon, Parmentiercaro7, stephan1Rambaud,
victorcatteau, philippevardon, MessihaOfficiel, HdeLesquen) et **3 homonymes**
(audience dérisoire : thierryperez43, lepapacito, JulienRochedy) → à corriger
dans `data/pool_rn_udr.json`. 1 compte réel à timeline syndication vide
(MichleMartinez3) → repli automatique Wayback CDX → fxtwitter ajouté au collecteur.

## Refonte visuelle (26/08, soir)
Le front d'origine cochait 9 motifs anti-slop (accent violet + dégradé
bleu-violet, fond radial, Inter, arrondis uniformes, emojis décoratifs,
Tailwind CDN). Refait entièrement : `static/design.css` porte le système
(registre d'archive — papier chaud + thème sombre, Newsreader / IBM Plex Sans /
IBM Plex Mono à rôles stricts, un seul accent bleu d'encre, filets au lieu de
cartes). Charte documentée dans `DESIGN.md` à la racine.

Gains mesurables : le CDN Tailwind (~3 Mo de JS + FOUC) disparaît au profit de
22 ko de CSS ; le masthead, dupliqué dans les 4 pages, vit désormais dans
`common.js` ; `compteur.js` ne redéclare plus `API`/`$` (conflit de const avec
common.js). Le lecteur d'article devient un vrai dialogue (focus déplacé,
Escape, focus rendu). Vérifié : 0 classe CSS orpheline, 0 variable manquante,
ids HTML ↔ sélecteurs JS cohérents sur les 4 pages, 10/10 routes servies en 200.

## Chaîne d'analyse : calibration sur corpus réel (27/08)
Trois défauts structurels trouvés en faisant tourner la chaîne sur 3 751
déclarations — aucun n'était visible en tests unitaires :

1. **Embeddings** : `model.encode` sur 3 000+ textes tuait le process avec un
   code de sortie 0 trompeur. Encodage par lots de 128. 564 → 3 751 embeddings.
2. **Passe normative déterministe DÉSARMÉE** : 553 arêtes produites, 553
   fausses. `stance_polarity` est produit sur une déclaration isolée — « voté
   POUR la censure du budget » et « CONTRE ce budget » sortent opposés alors
   qu'ils s'accordent. Une file inondée de faux positifs coûte plus qu'une file
   vide : le relecteur cesse de la lire. Mécanique conservée derrière un flag.
3. **Fenêtre de similarité calibrée** (0,55→0,78 / 0,97→0,93) sur la
   distribution réelle (212 102 paires : médiane 0,21, p90 0,44). Le juge
   recevait 5 412 paires sans objet commun ; il en reçoit 104 bien formées.
   Plus : exclusion des paires de même source (deux segmentations d'un même
   propos ne se contredisent pas) et écart minimal de 7 jours entre deux propos
   du même locuteur. Classement par potentiel de revirement (même locuteur +
   écart temporel) au lieu de la similarité, qui remontait les redites.

**Résultat honnête : 0 contradiction sur 104 paires bien formées.** Ce n'est pas
un bug, c'est la réponse juste sur ce corpus — et elle vaut mieux que 553 faux
positifs. La cause est la profondeur temporelle : Marine Le Pen n'a que 14 mois
d'historique (06/2025 → 08/2026), Chenu 23 mois. On ne lit pas un revirement sur
14 mois de communication de campagne répétitive. Bardella a 3 781 statuts
archivés depuis 2023 ; on en a tiré 300.
