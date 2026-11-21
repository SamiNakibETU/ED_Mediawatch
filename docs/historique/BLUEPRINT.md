# BLUEPRINT — l'ambition complète (vision longue, horizon 2027 et au-delà)

> Prolonge `VISION_PRODUIT.md` (L0-L4) et `specs.md`. Objectif : voir loin,
> anticiper tout. Le socle reste le **Grand Livre exhaustif** ; ce document décrit
> où on va une fois qu'il existe — et tout ce qu'il faut prévoir pour y arriver.

## 0. North star élargi
De « veille ED » à **le système de référence, faisant autorité, de la cohérence du
discours politique** : exhaustif, sourcé, archivé, longitudinal, multicouche — un
*« GPS de la parole publique »*. Périmètre de lancement : RN/ED pour 2027. **La
méthode est le produit** → généralisable (autre famille, autre pays, autre langue).

---

## 1. Substrat OMNICANAL — capter VRAIMENT tout (pas seulement X + presse)
Une figure ED parle partout. Le Grand Livre doit ingérer **tous les canaux**, chacun
réduit à des **déclarations datées + diarisées + sourcées + archivées** :
- **X** (posts/replies/quotes/engagement) — fait.
- **Presse** (60 sources, intégral via scraper) — fait.
- **TV / Radio** : CNews, BFM, France Inter, Europe 1, LCI… → **ASR (Whisper)** +
  diarisation (qui parle) → transcript horodaté. *Énorme volume ED non capté aujourd'hui.*
- **Vidéo** : YouTube, TikTok, **TV Libertés, Livre Noir, Omerta, Frontières** → ASR.
- **Podcasts**.
- **Institutionnel** : Assemblée / Sénat (interventions en hémicycle, **votes**,
  questions au gouvernement, amendements) — la parole *officielle* + le vote réel.
- **Officiel parti** : communiqués, **programmes**, tribunes, sites RN/UDR/Reconquête.
- **Débats** (présidentiels, législatifs).

> Chaque canal = un adaptateur d'ingestion qui converge vers la **même unité
> déclaration**. L'ASR (audio/vidéo → texte) est la grande extension technique.

## 2. Le Grand Livre comme GRAPHE DE CONNAISSANCE temporel
Pas une table de claims : un **graphe** requêtable.
- **Entités** : personnalités, partis (affiliations **temporelles**), référents,
  thèmes, **événements** (attentat, motion, élection…), sources, **lieux** (carto).
- **Déclarations** (nœuds) reliées à : locuteur, source+reçu, événement déclencheur,
  référent, et **autres déclarations** (contradiction, écho, citation, réponse).
- **Temporel partout** : l'évolution d'une position est une requête, pas un calcul ad hoc.
- **Provenance** : chaque arête remonte au verbatim_span + snapshot + capture.

## 3. Intelligence multicouche L0 → L6 (élargie)
L0-L4 dans `VISION_PRODUIT.md`. On prolonge :
- **L0** Grand Livre exhaustif (déclarations **tous types**, **omnicanal**).
- **L1** Enrichissement : thème/stance (CamemBERT), référent (embeddings), **NER**,
  **émotion/valence**, **registre/violence verbale**, check-worthiness.
- **L2** Par personnalité : dossier vivant (RAG), revirements, obsessions, dérive.
- **L3** Par groupe/faction : contradictions intra/inter-parti, divergence (Wordfish),
  dérive de cadrage (fighting words + Wasserstein), **audit du programme**.
- **L4** Globale : graphe de contradictions, **indice de cohérence** publiable, radar
  des réactions, synthèses citables.
- **L5 — Réseau & coordination** : propagation des **éléments de langage** entre
  figures (qui lance un thème, qui relaie sous 24-48 h), détection de **messaging
  coordonné**, **agenda-setting** (presse↔X), cartographie d'influence, écho-chambers.
- **L6 — Anticipation** : modèles **prédictifs** (position probable d'une figure sur
  un nouvel enjeu, réaction-type à un événement), **détection précoce** de tensions
  internes / revirements en formation, **alertes** temps réel.

## 4. Orchestration AGENTIQUE — les gros modèles en continu
Une **intelligence multi-agent** tourne en permanence sur le graphe :
- **Agents spécialisés** : Analyste-par-figure · Chasseur-de-contradictions ·
  Analyste-de-cadrage · Détecteur-de-coordination · Vérificateur-externe
  (INSEE/Eurostat) · Rédacteur-de-synthèses-citables.
- **Superviseur** : oriente, priorise la **file de validation humaine**, arbitre le coût.
- **RAG hiérarchique** (map-reduce sur les déclarations : figure → groupe → global) —
  jamais tout le corpus dans un prompt.
- **Active learning** : chaque validation humaine recalibre seuils/prompts/classifieurs.
- **Batch + temps réel** : la masse en batch (coût/2), l'actualité chaude en flux.

## 5. Surfaces produit — la « war room 2027 »
Les 11 surfaces specs §6 + l'ambition :
- **War room temps réel** (vue campagne, par thème/figure/parti/jour).
- **Alertes** : revirement / contradiction / coordination détectés → notif journaliste.
- **Dossiers auto-générés** par figure (fact sheets citables, mis à jour en continu).
- **Briefs** quotidiens/hebdo (synthèse LLM sourcée).
- **« Ask the corpus »** : Q&A langage naturel sur le Grand Livre (RAG **avec
  provenance** — chaque réponse cite ses déclarations + reçus).
- **API + cartes citables** (PDF/image) pour partenaires presse.
- **Portail public de transparence** (selon posture, §décisions).
- **Le Compteur / Fil des revirements / Carte des positions / Audit programme /
  Radar / Indice de cohérence / Dérive du cadrage** (specs §6).

## 6. Crédibilité = le moat (ce qui rend l'outil citable)
Symétrie de méthode (**parti témoin**), seuils **précision > rappel**,
**human-in-the-loop** avant publication, **fidélité au verbatim**, accord LLM/humain
reporté (**κ**), méthode **versionnée + datée**, **RGPD** (propos publics politiques),
**auditabilité bout-en-bout**. Différenciation : verticalité (cohérence
programmatique) là où un prompt est stateless et Arlequin horizontal/non supervisé.

## 7. Infra & MLOps — tenir la charge sur 18 mois
- **pgvector** (blocking/retrieval), embeddings **benchmarkés** (BGE-M3 / e5-large /
  Solon / Cohere) sur données réelles.
- **LLM tiering** : tier-1 cheap (check-worthiness + segmentation), tier-2 capable
  (fidélité + publication), **batch API** (coût/2). **Cache + dédup near-dup** (fait).
- **ASR** (Whisper) pour audio/vidéo ; diarisation.
- **Orchestration** (Prefect/Dagster) : reprises sur erreur, suivi multi-étapes.
- **Object storage** (reçus + captures). **Observabilité** (freshness/collectors/
  collection-report déjà là → étendre coût LLM, latence, qualité).
- **Backfill historique** (programmes + déclarations 2022→) pour l'audit programme et
  la profondeur du graphe.

## 8. Risques anticipés → mitigations (prévoir tout)
| Risque | Mitigation |
|---|---|
| **Accès X / Nitter** (point de défaillance n°1) | self-host + rotation sessions ; fallback RSS ; budget API officielle si besoin |
| **Coût LLM explosif** | tiering, batch, cache, dédup, CamemBERT pour la masse |
| **IP datacenter blacklistée** (presse) | scraper-service curl_cffi (fait) + cookies + proxy résidentiel si besoin |
| **Faux positifs → crédibilité ruinée** | précision>rappel, LLM filtre, human-in-the-loop, κ |
| **Comptes X suspendus** (sessions) | comptes jetables multiples + rotation |
| **Contenu supprimé** | reçus (snapshot + Wayback SPN, fait) |
| **Accusation de biais** | symétrie de méthode + parti témoin, doc publique |
| **RGPD** | propos publics, finalité veille/recherche, archivage propre |
| **Évasion linguistique** (figures changent de mots) | dérive de cadrage (fighting words) détecte le glissement |
| **Dérive des modèles** | méthode/prompts versionnés, rejouables |

## 9. Phasage réaliste (de maintenant à 2027)
- **Fait** : collecte consolidée (X+presse, scraper anti-paywall, C0 métadonnées,
  typologie, genre, archivage, 60 sources, observabilité, nettoyage), pipeline
  d'analyse quantitatif live + correctif précision, substrat embeddings.
- **Maintenant → L0** : **extraction GÉNÉRALE de déclarations** (tous types, LLM
  contraint par schéma, tiering) → Grand Livre exhaustif + surface navigable.
- **Puis L1-L2** : CamemBERT masse + embeddings/référent ; dossiers par personnalité.
- **Puis L3-L4** : contradictions toutes-types (NLI + LLM), graphe, indice de cohérence.
- **Puis L5-L6** : coordination/agenda-setting, anticipation, alertes.
- **Extensions** : omnicanal (ASR TV/radio/vidéo), fact-check externe, war room,
  API partenaires, portail public.
- **Au-delà 2027** : généralisation méthode (autre famille/pays), partenariats
  académiques (open-method, citable).

---
**Invariant** : tout est une **couche recalculable** sur le verbatim archivé, jamais
re-collectée ; tout finding remonte à sa preuve ; l'humain garde l'interprétation.
