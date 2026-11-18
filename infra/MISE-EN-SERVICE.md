# Mettre ED Mediawatch en service sur un serveur Hetzner

> **18/11/2026 : voie abandonnée au profit d'une mise en ligne gratuite, sans serveur**
> (`pages/README.md`). Ce document reste comme option si un serveur devenait nécessaire.

Décision du 17 novembre 2026 : l'application Railway a disparu (« Application not found ») sans sauvegarde de sa base.
ED Mediawatch passe sur un serveur à soi, qui fait tout tourner : l'application, sa base PostgreSQL, le Nitter local,
la sauvegarde de nuit et l'accès protégé. Coût : environ 7 € par mois.

Les étapes marquées **Sami** demandent un paiement, un compte ou un secret : un agent ne les fait pas.

## 1. Commander le serveur (Sami, 10 minutes)

1. Console Hetzner, projet existant : nouveau serveur **CX23** (2 vCPU, 4 Go), Ubuntu 24.04, Nuremberg ou Falkenstein.
   Le CPX12 de `vpn-sami` (2 Go) ne convient pas : c'est la passerelle d'accès à Whitebeard et à L'Orient-Le Jour,
   on n'y touche pas.
2. Clé SSH : la même que pour `vpn-sami`.
3. Activer la protection contre la suppression.
4. Noter l'adresse IPv4 : elle donne l'adresse du site, `<ip>.sslip.io`, sans acheter de domaine.

## 2. Préparer la machine (Sami, ou un agent par SSH avec ton accord)

```bash
ssh root@<ip>
apt update && apt -y upgrade && apt -y install docker.io docker-compose-v2 git ufw
ufw allow OpenSSH && ufw allow 80 && ufw allow 443 && ufw --force enable
adduser --disabled-password --gecos "" edmw && usermod -aG docker edmw
```

## 3. Récupérer le code (Sami : le dépôt est privé)

```bash
su - edmw
git clone https://github.com/SamiNakibETU/ED_Mediawatch.git
cd ED_Mediawatch/infra
mkdir -p backups/expirees
```

## 4. Nitter local (Sami, 20 minutes)

```bash
git clone https://codeberg.org/shitter/shitter ~/shitter && docker build -t shitter:local ~/shitter
cp nitter.local.conf.example nitter.conf        # changer hmacKey ; redisHost = nitter-redis ; port 8080
```
Écrire `sessions.jsonl` à la main avec deux ou trois comptes X dédiés (pas ton compte personnel), comme expliqué dans
`NITTER-LOCAL.md`. Ces deux fichiers ne quittent jamais le serveur.

## 5. Les secrets (Sami)

Copier `env.prod.example` en `.env.prod` et le remplir :
- `SITE_ADDRESS` : `<ip>.sslip.io`, et `CORS_ORIGINS` : `https://<ip>.sslip.io` ;
- `BASIC_AUTH_HASH` : `docker run --rm caddy:2 caddy hash-password --plaintext '<mot de passe>'` ;
- `POSTGRES_PASSWORD` et `API_TOKEN` : `openssl rand -hex 24` chacun ;
- `OPENROUTER_API_KEY` : une clé créée pour ce projet seul, avec un crédit de 30 $.

Les variables de Caddy et de la base sont aussi lues par Docker Compose : lancer avec `--env-file .env.prod`.

## 6. Lancer

```bash
docker compose -f docker-compose.prod.yml --env-file .env.prod up -d --build
docker compose -f docker-compose.prod.yml ps
curl -u terranova:<mot de passe> https://<ip>.sslip.io/health/freshness
```

## 7. Remettre les données (depuis le PC de Sami)

Les tweets collectés en local partent vers la nouvelle base ; la plateforme écarte les doublons, on peut relancer.

```powershell
cd D:\Sami\terra-nova\etudes\ed-mediawatch\code\backend
$env:ED_URL = "https://<ip>.sslip.io"; $env:API_TOKEN = "<API_TOKEN>"
python -m src.scripts.historique_x --pool --envoyer-archives    # historique par recherche (87 090 tweets)
python -m src.scripts.timeline_ed --envoyer                      # historique par les pages de profil
```
`/collect/*` passe sans le mot de passe de Caddy : le backend y exige le jeton `API_TOKEN`. Vérifier ensuite le
nombre de tweets par figure sur la page Couverture.

## 8. Sauvegardes

- La base est sauvegardée chaque nuit dans `infra/backups/` ; au-delà de 56 jours, les copies passent dans
  `backups/expirees/` (rien n'est effacé).
- Rapatrier chaque semaine la dernière copie sur le PC, dans le dépôt Kopia :
  `scp edmw@<ip>:ED_Mediawatch/infra/backups/edmw_<date>.dump D:\Sami\terra-nova\etudes\ed-mediawatch\donnees\sauvegardes\`
- Restaurer : `docker compose exec -T db pg_restore -U edmw -d edmw --clean < edmw_<date>.dump`.

## 9. Reste à régler au premier lancement

- Planifier `pipeline` (lecture par les modèles) une fois le référentiel validé (étape 4 du plan).
