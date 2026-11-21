# Charte visuelle — ED Mediawatch

Source unique : `backend/static/design.css`. Toute valeur ci-dessous existe comme
token CSS ; aucune valeur littérale ne doit apparaître ailleurs.

## Le principe

**Registre d'archive, pas tableau de bord.** Le produit consigne des propos
datés, attribués, sourcés, destinés à être opposés à leurs auteurs. La forme
doit dire « pièce au dossier ». Un observatoire dont l'interface ressemble à un
SaaS générique perd la crédibilité qui est sa seule arme.

Corollaire opérationnel : **une surface ne s'entoure pas, elle se sépare.** Les
entrées du registre sont séparées par des filets d'1 px. La carte n'existe que
là où la carte EST l'interaction — la file de validation, où chaque bloc est une
décision à prendre.

## Typographie — trois familles, trois rôles stricts

| Famille | Rôle | Jamais utilisée pour |
|---|---|---|
| **Newsreader** | titres, verbatim, corps de lecture | interface, données |
| **IBM Plex Sans** | navigation, boutons, étiquettes | corps de lecture |
| **IBM Plex Mono** | dates, compteurs, scores, identifiants (`tabular-nums`) | prose |

Échelle en quarte : 11 / 13 / 15 / 17 / 20 / 28 / 40 px (`--t-micro` → `--t-display`).
Aucune taille hors échelle. Mesure de lecture bornée à 40 rem (~66 caractères).

## Couleur

**Un seul accent** : bleu d'encre `--accent`. Il marque l'onglet actif, l'action
principale, le lien. Rien d'autre.

Le reste est un **encodage de données**, jamais une décoration :
- statut — `--ok` validé, `--pending` en attente, `--alert` contradiction ;
- famille politique — `--grp-rn`, `--grp-udr`, `--grp-figure`.

Règle absolue : **jamais de couleur seule.** Toute couleur porteuse de sens est
doublée d'un libellé lisible (8 % des hommes ont une déficience rouge-vert, et
un lecteur pressé ne décode pas une palette).

Deux thèmes complets, tokens redéfinis pour les trois états : `:root` (clair),
`@media (prefers-color-scheme: dark)` guardé par `:not([data-theme="light"])`,
et `:root[data-theme="dark"]` pour que la bascule gagne dans les deux sens.

## Interdits (liste anti-slop)

Ce que le front d'origine faisait et qui ne doit pas revenir :

1. dégradés violet/indigo, accent `#7c3aed` ;
2. fond en dégradé radial décoratif ;
3. Inter / `system-ui` comme police principale ;
4. rayon arrondi uniforme sur tout (`rounded-xl` partout) ;
5. emojis comme éléments graphiques (♥ 🔁 💬 🗎) ;
6. grille de 3 cartes à icône dans un cercle coloré ;
7. tout centré ;
8. bordure gauche colorée comme décor de carte ;
9. Tailwind par CDN (FOUC, poids, config dupliquée dans chaque page).

## Accessibilité — non négociable

- Focus visible partout (`:focus-visible`, jamais `outline: none` sans remplacement).
- Cibles tactiles ≥ 44 px sur les actions (fermeture du lecteur, boutons de décision).
- Corps de texte ≥ 15 px, prose de lecture à 17 px.
- Distinction lien visité préservée.
- `prefers-reduced-motion` coupe toute animation.
- Le lecteur d'article est un `dialog` : focus déplacé à l'ouverture, `Escape`
  ferme, focus rendu à l'élément d'origine.

## Mouvement

Deux motions, pas plus : l'entrée d'une entrée du registre (`.enter`, 200 ms) et
l'ouverture du panneau de lecture. Uniquement `transform` et `opacity`.

## Écriture d'interface

Les messages d'erreur disent ce qui a échoué **et** quoi faire. Les états vides
expliquent pourquoi c'est vide plutôt que d'afficher « Aucun résultat ». La file
de validation rappelle en tête que la machine propose et que l'humain tranche —
c'est une garantie produit, pas une politesse.

## Structure des fichiers

```
backend/static/
  design.css          tout le système (tokens, thèmes, composants)
  common.js           masthead, bascule de thème, helpers, arbre thématique
  index.html/app.js           registre X
  presse.html/presse.js       revue de presse + lecteur
  compteur.html/compteur.js   Le Compteur (Chart.js, couleurs lues des tokens)
  contradictions.html/…js     file de validation
```

Le masthead vit dans `common.js` : une seule source pour les quatre pages.
