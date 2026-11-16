#!/bin/sh
# Certbot renews in the existing container. Reload only when the relay cert changes.
set -eu
cd /home/ubuntu/apps/telegram_relay
current=$(docker exec webadb-nginx-1 sha256sum /etc/letsencrypt/live/relay.jetourtools.com/fullchain.pem)
previous=$(cat .certificate-loaded 2>/dev/null || true)
if [ "$current" != "$previous" ]; then
    docker exec webadb-nginx-1 nginx -t
    docker exec webadb-nginx-1 nginx -s reload
    printf '%s\n' "$current" > .certificate-loaded
fi
