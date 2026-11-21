# Méthodologie d'analyse — ED · MediaWatch

Cadre la phase **analyse** (après la collecte, désormais consolidée + nettoyée).
Ancré sur l'état de l'art (arXiv 2024-2026) et les garde-fous crédibilité du
ROADMAP (§6 : précision > rappel, human-in-the-loop, fidélité au verbatim,
méthode versionnée).

## 0. Principe : substrat propre d'abord
On ne raffine que sur un substrat dont on **connaît la qualité**. D'où, fait avant
toute analyse :
- **Nettoyage analyse-ready** (`text_clean.clean_article_text`) : retrait des
  liens et du hors-article (« Lire aussi », partage, crédits, temps de lecture),
  **sans toucher au verbatim**. Rejouable sur l'existant (`src.scripts.clean_articles`).
- **Métadonnées qualité** (C0) : `extraction_method`, `is_full_text`, `paywalled`,
  langue, date (jamais NULL, `published_estimated`), typologie X (RT/quote/reply),
  genre presse (interview/tribune).
- **Porte chiffrée** (`/health/collection-report`) : couverture / complétude /
  archivage / fraîcheur → on bascule sur l'analyse quand c'est au vert.

## 1. Pipeline recommandé (hybride NLP + LLM)
L'état de l'art converge : **BERT fine-tuné = classification de masse cohérente**
(thème, stance) ; **LLM = extraction/canonicalisation nuancée mais à valider**
(les LLM sont flexibles mais inconsistants/biaisés en classification directe).

1. **Segmentation en unités de claim** : découper post/article en assertions
   atomiques datées + attribuées (le claim = unité du graphe, cf ROADMAP §0).
2. **Classification thématique** (grille CAP déjà en place) → à industrialiser
   avec **CamemBERT 2.0** fine-tuné (réemploi du pipeline CamemBERT du projet
   Paris). Cohérent, reproductible, peu coûteux à l'échelle.
3. **Extraction de claims quantitatifs/normatifs** → **LLM contraint par schéma**
   (valeur, unité, référent, horizon) + **classification dans un référentiel
   FERMÉ** (on range, on ne génère pas les `referent_key`). Cerebras/Anthropic,
   validation humaine.
4. **Stance / position** par référent → BERT fine-tuné (X-Stance/HIPE couvrent le
   français) ; LLM en appui sur les cas ambigus.
5. **Détection d'incohérences** (types 1 revirement / 2 intra-parti / 3 inter-partis
   / 6 variance) → champ émergent avec **benchmark dédié** (ICWSM 2025). Blocking
   sémantique par référent via **embeddings Cohere** (déjà branchés) → comparaison
   intra-référent → file de validation humaine (déjà en place).
6. **Cadrage / framing** (extension) : fighting words, divergence de cadrage
   (Wasserstein) — réemploi du projet israélo-palestinien.

## 2. Préparation des données (ce qui alimente 1.)
- **Dédup sémantique** : `content_hash` (déjà posé) pour reposts/quasi-doublons ;
  embeddings pour le near-dup.
- **Langue** : champ `lang` (défaut fr) → filtrer/segmenter.
- **Normalisation conservatrice** : espaces/entités déjà gérés ; **ne pas**
  réécrire la prose (fidélité verbatim).
- **Couches recalculables** : thèmes, claims, stance, contradictions = couches
  **rejouables** sur le verbatim stocké, versionnées (jamais re-collecter).

## 3. Évaluation (non négociable)
- **Annotation humaine** + accord inter-annotateurs (**Cohen's κ**) sur échantillon
  (scripts réutilisables du projet Paris) avant d'industrialiser un classifieur.
- **Seuils conservateurs** (précision > rappel) ; tout ce qui est publié passe par
  **validation humaine**.
- Méthode **versionnée** (référentiel thématique déjà versionné).

## 4. Références (arXiv / actes)
- LLM & Stance Detection — survey 2025 : https://arxiv.org/abs/2505.08464
- Stance Detection, guide pratique (croyances politiques) : https://arxiv.org/abs/2305.01723
- Language Models Learn Metadata (stance politique) : https://arxiv.org/abs/2409.13756
- A Benchmark for Political Inconsistencies Detection (ICWSM 2025) :
  https://workshop-proceedings.icwsm.org/pdf/2025_29.pdf
- Political Leaning & Politicalness Classification : https://arxiv.org/abs/2507.13913
- CamemBERT-large pour le stance en presse FR (interrogative stances) :
  https://arxiv.org/abs/2603.21823
- LLMs in Argument Mining — survey : https://arxiv.org/abs/2506.16383

> Prochaines briques concrètes : industrialiser la classification thématique
> (CamemBERT fine-tuné), brancher le blocking embeddings réel (pgvector), étendre
> la détection d'incohérences sur le corpus nettoyé.
