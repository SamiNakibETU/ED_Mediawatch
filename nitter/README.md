# Nitter self-hosté sur Railway — engagement X

Débloque l'**engagement** (likes/RT/quote/reply) + **date exacte** + **backfill**
pour la collecte X. Le backend bascule automatiquement sur le HTML (avec
engagement) dès que `NITTER_SELF_HOSTED` pointe ce service.

`sessions.jsonl` (tes comptes X) **n'est jamais committé** : injecté au démarrage
via la variable d'env `NITTER_SESSIONS`.

## 1. Redis (requis par Nitter)
Dans le projet Railway : **+ New → Database → Redis**. Note ses variables
(`REDISHOST`, `REDISPORT`, `REDISPASSWORD`) — on les référencera.

## 2. Service Nitter
**+ New → GitHub Repo** (même repo `ED_Mediawatch`) → Settings :
- **Root Directory** = `nitter`
- Build auto (lit `railway.toml` → Dockerfile `FROM zedeus/nitter`).
- **Networking → Generate Domain** → note l'URL (ex. `https://ed-nitter.up.railway.app`).

### Variables du service Nitter
| Variable | Valeur |
|---|---|
| `NITTER_SESSIONS` | le **contenu** de ton `sessions.jsonl` (1 session JSON par ligne) — SECRET |
| `NITTER_HOSTNAME` | le domaine généré, sans `https://` (ex. `ed-nitter.up.railway.app`) |
| `REDIS_HOST` | `${{Redis.REDISHOST}}` |
| `REDIS_PORT` | `${{Redis.REDISPORT}}` |
| `REDIS_PASSWORD` | `${{Redis.REDISPASSWORD}}` |
| `NITTER_HMAC` | (optionnel) une chaîne aléatoire ; sinon générée au boot |

> `${{Redis.*}}` = *reference variables* Railway (adapte `Redis` au nom réel de
> ton service Redis).

Vérifie : ouvre `https://<domaine-nitter>/J_Bardella` → la timeline doit s'afficher
**avec les compteurs likes/RT** (sinon `sessions.jsonl` est vide/invalide).

## 3. Brancher le backend
Service **backend** → Variables :
```
NITTER_SELF_HOSTED = https://<domaine-nitter>
```
Au prochain run, `run_collection` sonde le HTML, bascule en mode engagement, et
`python -m src.scripts.backfill_x` (via `railway ssh`) devient opérationnel.

## Obtenir sessions.jsonl
Nitter 2026 exige de vrais comptes X (guest tokens supprimés). Génère
`sessions.jsonl` avec l'outil officiel `zedeus/nitter` (script
`tools/get_session.py`, un compte X jetable → une ligne JSON). Garde ce fichier
SECRET (il est gitignoré localement).
