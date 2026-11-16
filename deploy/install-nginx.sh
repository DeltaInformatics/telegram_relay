#!/bin/sh
# Run from ~/apps/telegram_relay on this VPS after starting the relay.
set -eu
edge=webadb-nginx-1
template=/home/ubuntu/webadb/deploy/nginx/webadb.conf.template
backup="$HOME/apps/telegram_relay/nginx-backup-$(date +%Y%m%d%H%M%S)"
mkdir -p "$backup"
cp "$template" "$backup/webadb.conf.template"
docker cp "$edge:/etc/nginx/conf.d/webadb.conf" "$backup/webadb.conf"
if grep -q 'server_name relay.jetourtools.com;' "$template"; then
    echo 'Relay already present; inspect existing configuration before rerunning.' >&2
    exit 1
fi
# Both the template and rendered config need updating: the template survives recreation.
install_config() {
    cat "$backup/webadb.conf" "$1" > "$backup/candidate.conf"
    docker cp "$backup/candidate.conf" "$edge:/etc/nginx/conf.d/webadb.conf"
    if ! docker exec "$edge" nginx -t; then
        docker cp "$backup/webadb.conf" "$edge:/etc/nginx/conf.d/webadb.conf"
        exit 1
    fi
    docker exec "$edge" nginx -s reload
}
install_config deploy/relay-http.conf
docker run --rm --volumes-from webadb-certbot-1 certbot/certbot:latest certonly \
    --webroot -w /var/www/certbot --non-interactive --agree-tos \
    --register-unsafely-without-email --cert-name relay.jetourtools.com \
    -d relay.jetourtools.com
cat deploy/relay-http.conf deploy/relay-https.conf > "$backup/relay.conf"
install_config "$backup/relay.conf"
cat "$backup/relay.conf" >> "$template"
echo "Nginx backup: $backup"
