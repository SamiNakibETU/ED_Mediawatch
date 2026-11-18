# Mettre ED Mediawatch en ligne sans serveur

Décision du 18 novembre 2026 : pas de serveur loué. Tout se calcule sur le poste de Sami, comme
Mot de la semaine, et le site part chaque semaine sur Cloudflare Pages, gratuit, fermé par un
compte par relecteur.

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

## Mise en place, une fois (faite le 18/11/2026)

1. Projet Pages `ed-mediawatch` et espace KV des décisions : `python -m src.scripts.publier_site --creer`.
2. Un compte par relecteur : `python -m src.scripts.publier_site --relecteur NOM`. Le mot de passe
   est tiré au hasard et noté dans `admin/acces-relecteurs.txt` de l'étude (hors du dépôt) ; seule
   son empreinte part chez Cloudflare (secret `RELECTEURS`). Le nom du compte signe les décisions.
   Relancer la commande pour un nom existant renouvelle son mot de passe.
3. Cloudflare Access reste possible en plus (`ACCESS_TEAM` dans `wrangler.toml`), pas nécessaire.

Adresse : https://ed-mediawatch.pages.dev (le navigateur demande nom et mot de passe).

**Envoi par morceaux.** Le VPN du poste coupe les envois de plus d'environ 1 Mo vers Cloudflare
(constaté le 18/11/2026 : « other side closed »). `publier_site` envoie donc le site par morceaux
de 4 Mo par défaut ; avec le VPN actif, passer `--morceau-mo 0.4`.

## Chaque semaine

`python -m src.scripts.publier_site` fait trois choses dans l'ordre : il ramène les décisions
(`donnees/decisions/decisions.ndjson` en garde l'archive, avec le relecteur, la date et le motif),
il refait l'export (environ 40 secondes), il envoie.

## Pourquoi pas un serveur

Un serveur (voir `../MISE-EN-SERVICE.md`, l'ancienne voie Hetzner) coûte environ 7 € par mois
et demande de l'entretien. Le site figé suffit pour lire et relire : les calculs lourds tournent
déjà sur le poste, et les relecteurs ne passent qu'une fois par semaine.
