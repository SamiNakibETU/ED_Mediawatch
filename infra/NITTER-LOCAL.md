# Nitter local dans WSL, avec nos comptes X

But : ne plus dépendre de xitter.cf pour l'historique, les réponses et les profils. Les scripts
`historique_x` et `conversation_x` lisent n'importe quelle instance : il suffit de leur passer
`--instance http://localhost:8082`.

## Ce qu'il faut savoir avant

- **Les comptes peuvent être suspendus.** X interdit la lecture automatique dans ses conditions
  d'utilisation. Prendre des comptes dédiés à la recherche, jamais un compte personnel ni les
  comptes de collecte de Mot de la semaine. Un compte ancien, avec téléphone et double
  authentification, résiste mieux qu'un compte neuf.
- **Le débit dépend du nombre de comptes.** Chaque compte a un quota de recherches par quart d'heure
  (de l'ordre de 50 d'après la documentation de twscrape ; à mesurer). Avec deux comptes, il faut
  compter environ une recherche toutes les 9 secondes, soit moins que sur xitter.cf, qui répartit
  la charge sur ses propres comptes. Le gain, c'est l'indépendance, pas la vitesse.
- **Aucun secret dans le dépôt.** `nitter.conf` et `sessions.jsonl` sont gitignorés
  (`git check-ignore -v infra/sessions.jsonl` doit répondre).

## 1. Docker dans Ubuntu (WSL), une fois

```bash
sudo apt update && sudo apt install -y docker.io docker-compose-v2 git openssl
sudo usermod -aG docker $USER
```

Fermer puis rouvrir le terminal Ubuntu (ou `wsl --shutdown` depuis Windows), puis vérifier :
`docker run --rm hello-world`.

## 2. Construire l'image

```bash
git clone https://codeberg.org/shitter/shitter ~/shitter
docker build -t shitter:local ~/shitter
```

Pour mettre à jour plus tard : `git -C ~/shitter pull && docker build -t shitter:local ~/shitter`,
puis relancer le service (étape 5).

## 3. La configuration

```bash
cd /mnt/d/Sami/terra-nova/etudes/ed-mediawatch/code/infra
cp nitter.local.conf.example nitter.conf
sed -i "s/A-CHANGER/$(openssl rand -hex 32)/" nitter.conf
```

## 4. Les sessions (à faire soi-même, compte par compte)

Pour chaque compte :

1. Ouvrir une **fenêtre de navigation privée**, se connecter à x.com avec le compte.
2. Outils de développement (F12) → Application → Cookies → `https://x.com`.
3. Copier les valeurs de `auth_token` et de `ct0`.
4. **Fermer la fenêtre sans se déconnecter** : la déconnexion invalide `auth_token`.

Puis écrire une ligne par compte dans `infra/sessions.jsonl` :

```json
{"kind": "cookie", "username": "compte1", "auth_token": "...", "ct0": "..."}
{"kind": "cookie", "username": "compte2", "auth_token": "...", "ct0": "..."}
```

Ces deux valeurs valent un mot de passe : ne les coller nulle part ailleurs (ni chat, ni mail, ni
note). Une session expire au bout de quelques semaines ou si le compte se déconnecte : refaire
l'étape pour ce compte.

## 5. Lancer, vérifier

```bash
cd /mnt/d/Sami/terra-nova/etudes/ed-mediawatch/code/infra
docker compose -f docker-compose.nitter.yml up -d
docker logs --tail 30 edmw-nitter
curl -s "http://localhost:8082/search?f=tweets&q=from%3AMLP_officiel" | grep -c timeline-item
```

Le dernier chiffre doit dépasser 0. Depuis Windows, `http://localhost:8082/MLP_officiel` s'ouvre
aussi dans le navigateur (WSL2 relaie localhost).

Arrêter : `docker compose -f docker-compose.nitter.yml down` (les données Redis restent dans
`nitter_redis/`).

## 6. Collecter

Depuis `code\backend`, sous Windows :

```
python -m src.scripts.historique_x --instance http://localhost:8082 --pause 9 --sans-envoi
python -m src.scripts.conversation_x URL --instance http://localhost:8082 --pause 9
```

Commencer par un seul compte et un mois connu (Marine Le Pen, juin 2024 : 258 tweets originaux,
étalon de l'annexe IRIS 04) pour vérifier que l'instance locale rend la même chose que xitter.cf.
Si les refus s'enchaînent (`HTTP 429`), les scripts ralentissent puis s'arrêtent d'eux-mêmes :
augmenter `--pause`, ne pas ajouter de comptes à la hâte.
