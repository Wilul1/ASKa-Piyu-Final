#!/usr/bin/env bash
# Renew Let's Encrypt certs and reload Compose nginx.
#
# Preferred (webroot — nginx stays up):
#   DOMAIN=api.your.edu ./scripts/renew_letsencrypt_certs.sh
#
# Standalone (stops nginx briefly; use if certs were issued with --standalone):
#   DOMAIN=api.your.edu ASKA_CERTBOT_STANDALONE=1 CERTBOT_EMAIL=you@your.edu \
#     ./scripts/renew_letsencrypt_certs.sh
#
# Cron (webroot — recommended once ACME webroot is mounted):
#   15 3 * * * DOMAIN=api.your.edu /opt/ASKa-piyu/scripts/renew_letsencrypt_certs.sh >> /var/log/aska-cert-renew.log 2>&1
#
# Cron (standalone):
#   15 3 * * * DOMAIN=api.your.edu ASKA_CERTBOT_STANDALONE=1 /opt/ASKa-piyu/scripts/renew_letsencrypt_certs.sh >> /var/log/aska-cert-renew.log 2>&1

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DOMAIN="${DOMAIN:-}"
WEBROOT="${ASKA_CERTBOT_WEBROOT:-$ROOT/deploy/certbot-www}"
COMPOSE=(docker compose --profile full -f "$ROOT/docker-compose.yml" -f "$ROOT/docker-compose.https.yml")

if [[ -z "$DOMAIN" ]]; then
  echo "ERROR: set DOMAIN=api.your.edu" >&2
  exit 1
fi

mkdir -p "$WEBROOT"

if [[ "${ASKA_CERTBOT_STANDALONE:-}" == "1" ]]; then
  echo "Renewing with certbot standalone (nginx will be stopped briefly)..."
  "${COMPOSE[@]}" stop nginx
  certbot renew --quiet --standalone || true
  if [[ ! -f "/etc/letsencrypt/live/${DOMAIN}/fullchain.pem" ]]; then
    certbot certonly --standalone -d "$DOMAIN" --non-interactive --agree-tos \
      -m "${CERTBOT_EMAIL:?Set CERTBOT_EMAIL for first-time issue}"
  fi
else
  echo "Renewing with certbot webroot at $WEBROOT ..."
  certbot renew --quiet --webroot -w "$WEBROOT" || true
  if [[ ! -f "/etc/letsencrypt/live/${DOMAIN}/fullchain.pem" ]]; then
    certbot certonly --webroot -w "$WEBROOT" -d "$DOMAIN" --non-interactive --agree-tos \
      -m "${CERTBOT_EMAIL:?Set CERTBOT_EMAIL for first-time issue}"
  fi
fi

install -m 644 "/etc/letsencrypt/live/${DOMAIN}/fullchain.pem" "$ROOT/deploy/certs/fullchain.pem"
install -m 600 "/etc/letsencrypt/live/${DOMAIN}/privkey.pem" "$ROOT/deploy/certs/privkey.pem"

"${COMPOSE[@]}" up -d nginx
"${COMPOSE[@]}" exec -T nginx nginx -s reload || "${COMPOSE[@]}" restart nginx

echo "Certs refreshed for ${DOMAIN} and nginx reloaded."
