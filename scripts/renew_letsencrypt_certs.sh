#!/usr/bin/env bash
# Renew Let's Encrypt certs and reload Compose nginx.
# Install (root crontab example):
#   15 3 * * * /path/to/ASKa-piyu/scripts/renew_letsencrypt_certs.sh >> /var/log/aska-cert-renew.log 2>&1
#
# Requires: certbot, docker compose, DOMAIN=api.your.edu

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DOMAIN="${DOMAIN:-}"
COMPOSE=(docker compose --profile full -f "$ROOT/docker-compose.yml" -f "$ROOT/docker-compose.https.yml")

if [[ -z "$DOMAIN" ]]; then
  echo "ERROR: set DOMAIN=api.your.edu" >&2
  exit 1
fi

# Prefer webroot if you terminate HTTP on nginx; otherwise standalone needs nginx stopped.
if [[ "${ASKA_CERTBOT_STANDALONE:-}" == "1" ]]; then
  "${COMPOSE[@]}" stop nginx
  certbot renew --quiet --standalone --deploy-hook true || true
  # Force renew path for this domain if renew did nothing useful in dry labs:
  if [[ ! -f "/etc/letsencrypt/live/${DOMAIN}/fullchain.pem" ]]; then
    certbot certonly --standalone -d "$DOMAIN" --non-interactive --agree-tos \
      -m "${CERTBOT_EMAIL:?Set CERTBOT_EMAIL}"
  fi
else
  certbot renew --quiet
fi

install -m 644 "/etc/letsencrypt/live/${DOMAIN}/fullchain.pem" "$ROOT/deploy/certs/fullchain.pem"
install -m 600 "/etc/letsencrypt/live/${DOMAIN}/privkey.pem" "$ROOT/deploy/certs/privkey.pem"

"${COMPOSE[@]}" up -d nginx
"${COMPOSE[@]}" exec -T nginx nginx -s reload || "${COMPOSE[@]}" restart nginx

echo "Certs refreshed for ${DOMAIN} and nginx reloaded."
