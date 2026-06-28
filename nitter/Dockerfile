# Nitter self-hosté pour Railway — débloque l'ENGAGEMENT X (likes/RT/quote/reply)
# + date exacte + backfill. Réutilise l'image zedeus/nitter (comme infra/ local).
#
# Le secret sessions.jsonl (comptes X) N'EST PAS dans l'image : il est injecté au
# démarrage depuis la variable d'env NITTER_SESSIONS par entrypoint.sh.
FROM zedeus/nitter:latest

USER root
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Railway injecte $PORT ; l'entrypoint génère nitter.conf + sessions.jsonl puis
# lance le binaire nitter (présent dans /src de l'image de base).
ENTRYPOINT ["/entrypoint.sh"]
