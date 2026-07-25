# TLS certificates for nginx HTTPS

Place your PEM files here (gitignored):

| File | Contents |
|------|----------|
| `fullchain.pem` | Certificate + intermediates (Let's Encrypt fullchain) |
| `privkey.pem` | Private key |

## Let's Encrypt (certbot on the host)

```bash
# Example — adjust domain and email for your campus.
sudo certbot certonly --standalone -d api.your.edu

sudo mkdir -p deploy/certs
sudo cp /etc/letsencrypt/live/api.your.edu/fullchain.pem deploy/certs/
sudo cp /etc/letsencrypt/live/api.your.edu/privkey.pem deploy/certs/
sudo chmod 644 deploy/certs/fullchain.pem
sudo chmod 600 deploy/certs/privkey.pem
```

Then start compose with TLS:

```bat
docker compose --profile full -f docker-compose.yml -f docker-compose.https.yml up -d --build
```

Point Flutter / `ASKA_CORS_ORIGINS` at `https://api.your.edu` (port 443).

## Automated renewal

Use [`scripts/renew_letsencrypt_certs.sh`](../../scripts/renew_letsencrypt_certs.sh) on a Linux VPS:

```bash
sudo chmod +x scripts/renew_letsencrypt_certs.sh
sudo DOMAIN=api.your.edu CERTBOT_EMAIL=you@your.edu ASKA_CERTBOT_STANDALONE=1 \
  ./scripts/renew_letsencrypt_certs.sh
```

Cron (daily check; certbot only renews near expiry):

```cron
15 3 * * * DOMAIN=api.your.edu /opt/ASKa-piyu/scripts/renew_letsencrypt_certs.sh >> /var/log/aska-cert-renew.log 2>&1
```

Self-signed lab certs from `scripts/bootstrap_campus_deploy.py` are **not** renewed by this script — replace them with Let's Encrypt before campus go-live.

## Campus / internal CA

Copy your issued cert chain to `fullchain.pem` and key to `privkey.pem` with the same names.
