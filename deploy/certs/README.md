# TLS certificates for nginx HTTPS

Place your PEM files here (gitignored):

| File | Contents |
|------|----------|
| `fullchain.pem` | Certificate + intermediates (Let's Encrypt fullchain) |
| `privkey.pem` | Private key |

HTTPS nginx also serves ACME HTTP-01 challenges from `deploy/certbot-www/` on port 80 (before redirecting everything else to HTTPS). That folder is mounted read-only into the nginx container.

## Let's Encrypt — preferred (webroot, nginx stays up)

With the HTTPS overlay running and DNS pointing at the VPS:

```bash
sudo mkdir -p deploy/certbot-www deploy/certs
sudo certbot certonly --webroot -w deploy/certbot-www -d api.your.edu \
  --agree-tos -m you@your.edu

sudo cp /etc/letsencrypt/live/api.your.edu/fullchain.pem deploy/certs/
sudo cp /etc/letsencrypt/live/api.your.edu/privkey.pem deploy/certs/
sudo chmod 644 deploy/certs/fullchain.pem
sudo chmod 600 deploy/certs/privkey.pem
```

Then (re)start:

```bash
docker compose --profile full -f docker-compose.yml -f docker-compose.https.yml up -d --build
```

Point Flutter / `ASKA_CORS_ORIGINS` at `https://api.your.edu`.

## Let's Encrypt — standalone (stops nginx)

Use only if webroot is unavailable (first boot before compose, or campus firewall quirks):

```bash
sudo docker compose --profile full -f docker-compose.yml -f docker-compose.https.yml stop nginx
sudo certbot certonly --standalone -d api.your.edu --agree-tos -m you@your.edu
sudo cp /etc/letsencrypt/live/api.your.edu/fullchain.pem deploy/certs/
sudo cp /etc/letsencrypt/live/api.your.edu/privkey.pem deploy/certs/
sudo docker compose --profile full -f docker-compose.yml -f docker-compose.https.yml up -d nginx
```

## Automated renewal

```bash
sudo chmod +x scripts/renew_letsencrypt_certs.sh
```

**Webroot cron (recommended):**

```cron
15 3 * * * DOMAIN=api.your.edu /opt/ASKa-piyu/scripts/renew_letsencrypt_certs.sh >> /var/log/aska-cert-renew.log 2>&1
```

**Standalone cron** (must set the flag — otherwise renew fails while nginx holds :80):

```cron
15 3 * * * DOMAIN=api.your.edu ASKA_CERTBOT_STANDALONE=1 CERTBOT_EMAIL=you@your.edu /opt/ASKa-piyu/scripts/renew_letsencrypt_certs.sh >> /var/log/aska-cert-renew.log 2>&1
```

Self-signed lab certs from `scripts/bootstrap_campus_deploy.py` are **not** renewed by this script — replace them with Let's Encrypt before campus go-live.

## Campus / internal CA

Copy your issued cert chain to `fullchain.pem` and key to `privkey.pem` with the same names.
