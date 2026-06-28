#!/bin/sh
# Génère nitter.conf (port Railway + Redis + hmac) et sessions.jsonl (depuis env,
# jamais committé), puis lance Nitter. Toute la config sensible vient des
# variables d'environnement Railway.
set -e
cd /src

: "${PORT:=8080}"
: "${NITTER_HOSTNAME:=localhost}"
: "${REDIS_HOST:=localhost}"
: "${REDIS_PORT:=6379}"
: "${REDIS_PASSWORD:=}"
# hmacKey : aléatoire si non fourni (od + /dev/urandom = dispo dans busybox alpine).
if [ -z "${NITTER_HMAC:-}" ]; then
  NITTER_HMAC=$(head -c 24 /dev/urandom | od -An -tx1 | tr -d ' \n')
fi

cat > /src/nitter.conf <<EOF
[Server]
hostname = "${NITTER_HOSTNAME}"
title = "nitter"
address = "0.0.0.0"
port = ${PORT}
https = false
httpMaxConnections = 100
staticDir = "./public"

[Cache]
listMinutes = 240
rssMinutes = 10
redisHost = "${REDIS_HOST}"
redisPort = ${REDIS_PORT}
redisPassword = "${REDIS_PASSWORD}"
redisConnections = 20
redisMaxConnections = 30

[Config]
hmacKey = "${NITTER_HMAC}"
base64Media = false
enableRSS = true
enableDebug = false
proxy = ""
proxyAuth = ""
tokenCount = 10

[Preferences]
theme = "Nitter"
replaceTwitter = ""
replaceYouTube = ""
replaceReddit = ""
proxyVideos = true
hlsPlayback = false
infiniteScroll = false
EOF

# sessions.jsonl (comptes X) depuis l'env — une session par ligne (JSONL).
if [ -n "${NITTER_SESSIONS:-}" ]; then
  printf '%s\n' "$NITTER_SESSIONS" > /src/sessions.jsonl
fi
if [ ! -s /src/sessions.jsonl ]; then
  echo "WARN: sessions.jsonl vide — Nitter ne servira pas les profils. Fournir NITTER_SESSIONS." >&2
fi

echo "nitter.start hostname=${NITTER_HOSTNAME} port=${PORT} redis=${REDIS_HOST}:${REDIS_PORT}"
exec ./nitter
