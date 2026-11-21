# Vision produit — Grand Livre exhaustif + Intelligence multicouche

> Pont entre l'état du code (extraction **quantitative** seule) et la vision des
> `specs.md` (§2, §6.2). Cap réaffirmé par l'user : **tout retenir d'abord** —
> chaque déclaration, de chaque personnalité, sur chaque source, à chaque date —
> puis empiler une **intelligence SOTA multicouche** (par figure → par groupe →
> globale). Le substrat exhaustif est le plus important ; l'analyse est une
> couche **recalculable** par-dessus (jamais re-collecter).

## 0. Principe : capter TOUT, filtrer JAMAIS (au substrat)
La valeur n'est pas le flux, c'est l'**accumulation longitudinale interrogeable**.
Donc la couche basse doit être **exhaustive et à fort rappel** : chaque prise de
parole d'une figure suivie devient une (ou plusieurs) **déclaration(s)
structurée(s)**, quel que soit le type. On ne jette rien au substrat ; on raffine,
note, classe, score **au-dessus**, de façon versionnée et rejouable.

## 1. L'unité : la déclaration (claim), TOUS types
Aujourd'hui on n'extrait que `factuel_quantitatif`. Le Grand Livre doit porter les
**5 types** (specs §2.2) :
- **factuel_quantitatif** — « le coût de l'immigration, c'est 80 Md€/an » → Le Compteur.
- **factuel_qualitatif** — « l'insécurité explose dans les villes moyennes ».
- **normatif** — « il faut rétablir la double peine » (position/valeur).
- **predictif** — « si rien n'est fait, ce sera le chaos en 2027 ».
- **attributif** — « la gauche a saboté le débat parlementaire ».

Chaque déclaration garde son **`verbatim_span` exact** (fidélité, garde-fou
légitimité) + une forme **canonique autoportante** (coréférences résolues, sans
ajout d'info absente — *molecular facts*, Gunjal & Durrett). Métadonnées :
speaker_id, parti-à-la-date, source+reçu, date exacte, thème/sous-thème,
`referent_key`, stance (cible/polarité/intensité), embedding.

> Conséquence : **chaque tweet/article est segmenté en déclarations par un LLM
> contraint par schéma** (extraction structurée). C'est « la couche claim », le
> travail neuf que les specs §8 identifient comme l'effort central.

## 2. Architecture d'intelligence multicouche (L0 → L4)
Chaque couche est **recalculable** sur la couche du dessous, **versionnée**, et
**validée humain** avant publication.

**L0 — Le Grand Livre (substrat exhaustif).** Toutes les déclarations structurées,
datées, sourcées, archivées (reçus). Navigable/requêtable par figure, parti, thème,
sous-thème, période, type, présence de chiffre. *C'est l'actif de recensement et de
légitimité ; tout s'y branche.* **Priorité absolue.**

**L1 — Enrichissement par déclaration.** Classification thème/sous-thème
(**CamemBERT** fine-tuné, masse, bas coût) ; stance (cible/polarité/intensité) ;
rattachement `referent_key` (embeddings + lexique) ; check-worthiness ; embedding
pgvector. LLM uniquement sur les cas durs / la publication (tiering coût, specs §5.2).

**L2 — Intelligence PAR PERSONNALITÉ.** Pour chaque figure, un **dossier vivant**
synthétisé par un gros modèle (RAG sur SES déclarations) : positions par thème dans
le temps, **revirements** (type 1), obsessions thématiques, évolution du cadrage,
indice de cohérence intra-locuteur, fréquence/engagement. « Bardella sur l'énergie :
l'évolution. »

**L3 — Intelligence PAR GROUPE/PARTI.** Agrégation par RN / UDR / Reconquête :
positions agrégées, **contradictions intra-parti** (type 2), **divergence
inter-partis** (type 3, carte des positions / Wordfish), **dérive de cadrage**
(fighting words log-odds + Wasserstein), **adhérence au programme** (type 4). Un
modèle synthétise la **cohérence d'une famille** sur un thème.

**L4 — Intelligence GLOBALE (« en entier »).** Raisonnement trans-corpus : **graphe
de contradictions** (nœuds=claims, arêtes typées 1-6 scorées) ; **indice de
cohérence** publiable (par parti×thème, défini/borné) ; **radar des réactions** à
l'actualité (presse↔X) ; narratifs émergents ; dérives temporelles. Un gros modèle
interroge le Grand Livre entier (RAG hiérarchique) pour produire des synthèses
citables.

## 3. Où interviennent les « gros modèles » (SOTA, multicouche)
- **Extraction (L0)** : LLM **contraint par schéma** (structured output) = SOTA
  pratique pour l'extraction FR à faible annotation. Tier-1 cheap (check-worthiness
  + segmentation), tier-2 capable (décontextualisation fidèle + tout ce qui se publie).
- **Classification de masse (L1)** : **CamemBERT 2.0** fine-tuné (cohérent, pas cher) ;
  **NLI FR** pour la contradiction normative au sein des blocs.
- **Blocking / retrieval (L1-L4)** : embeddings (BGE-M3 / e5-large / Solon / Cohere
  à benchmarker) + pgvector. *Le blocking par référent est le levier qualité n°1.*
- **Synthèse par niveau (L2-L4)** : RAG **hiérarchique** — on ne jette pas tout le
  corpus dans un prompt ; on récupère par figure/groupe/référent puis un gros modèle
  synthétise avec citations + provenance. Map-reduce sur les déclarations.
- **Contradiction (L4)** : variance numérique (déterministe, robuste) + jugement LLM
  par paire (avec justification + citation des 2 verbatims) pour le normatif et la publication.

## 4. Garde-fous (non négociables, specs §7)
Symétrie de méthode · seuils **précision > rappel** sur tout ce qui sort ·
**human-in-the-loop** avant publication · **fidélité au verbatim** · accord
LLM/humain reporté (κ) · méthode **versionnée** · RGPD (propos publics politiques).

## 5. Chemin concret — l'ordre qui respecte « tout retenir d'abord »
1. **Le Grand Livre exhaustif (L0)** — *maintenant le plus important.* Étendre
   l'extraction du quantitatif seul à **toutes les déclarations** (LLM contraint par
   schéma, tier-1 segmentation + tier-2 fidélité). Modèle `Claim` déjà prêt (champs
   stance/type présents). Surface « Grand Livre » navigable.
2. **L1 enrichissement** — CamemBERT thème/stance de masse + embeddings/référent.
3. **L2 dossiers par personnalité** (RAG) — la première intelligence « gros modèle ».
4. **L3 groupes/factions** — contradictions intra/inter-parti, dérive, programme.
5. **L4 global** — graphe, indice de cohérence, radar, synthèses citables.

> Le quantitatif (Le Compteur) déjà fait n'est qu'**un référent** de L4 ; il restait
> isolé faute de substrat exhaustif. On le replace comme une vue parmi d'autres une
> fois le Grand Livre rempli de **toutes** les déclarations.
