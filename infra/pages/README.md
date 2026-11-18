# Mettre ED Mediawatch en ligne sans serveur

Décision du 18 novembre 2026 : pas de serveur loué. Tout se calcule sur le poste de Sami, comme
Mot de la semaine, et le site part chaque semaine sur Cloudflare Pages, gratuit, derrière
Cloudflare Access.

## Ce qui tourne où

| Quoi | Où | Comment |
|---|---|---|
| Collecte X | poste de Sami | `timeline_ed`, `historique_x` (une instance à la fois) |
| Import en base | poste de Sami | `python -m src.scripts.importer_corpus` |
| Lecture des tweets | abonnement ChatGPT | `python -m src.scripts.lire_registre` (Codex CLI) |
| Pages en ligne | Cloudflare Pages | `python -m src.scripts.publier_site` |
| Décisions des relecteurs | Cloudflare (fonction + KV) | ramenées en base à chaque publication |

Ce que la version en ligne ne fait pas : les recherches libres, et le détail d'un moment cliqué
dans la série des thèmes. La page l'indique au lieu de rester bloquée.

## Mise en place, une fois

1. **Créer le projet et l'espace des décisions** (gratuit, depuis `code\backend`) :
   `python -m src.scripts.publier_site --creer`
2. **Sami, 5 minutes** : tableau de bord Cloudflare, Zero Trust, Access, Applications.
   Ajouter une application « self-hosted » pour `ed-mediawatch.pages.dev` (et
   `*.ed-mediawatch.pages.dev`), avec une politique qui liste les adresses des relecteurs.
   C'est la même démarche que pour Mot de la semaine.
3. Recopier dans `infra/pages/wrangler.toml` le nom d'équipe Access (`ACCESS_TEAM`, la partie
   avant `.cloudflareaccess.com`) et, si possible, l'AUD de l'application (`ACCESS_AUD`).
   Sans `ACCESS_TEAM`, la fonction refuse toute décision et `publier_site` refuse d'envoyer.
4. Première publication : `python -m src.scripts.publier_site`.

## Chaque semaine

`python -m src.scripts.publier_site` fait trois choses dans l'ordre : il ramène les décisions
(`donnees/decisions/decisions.ndjson` en garde l'archive, avec le relecteur, la date et le motif),
il refait l'export (environ 40 secondes), il envoie.

## Pourquoi pas un serveur

Un serveur (voir `../MISE-EN-SERVICE.md`, l'ancienne voie Hetzner) coûte environ 7 € par mois
et demande de l'entretien. Le site figé suffit pour lire et relire : les calculs lourds tournent
déjà sur le poste, et les relecteurs ne passent qu'une fois par semaine.
