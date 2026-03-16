#!/bin/bash
# Initialize Let's Encrypt certificates for marketing.dotmac.io
#
# Run once on first deploy:
#   chmod +x nginx/init-letsencrypt.sh && ./nginx/init-letsencrypt.sh
#
# Prerequisite: DNS for marketing.dotmac.io must point to this server.

set -euo pipefail

DOMAIN="marketing.dotmac.io"
EMAIL="${CERTBOT_EMAIL:-admin@dotmac.io}"
STAGING="${CERTBOT_STAGING:-0}"  # Set to 1 to test against staging servers

COMPOSE="docker compose"

# Check if cert already exists
if $COMPOSE run --rm certbot certificates 2>/dev/null | grep -q "$DOMAIN"; then
    echo "Certificate for $DOMAIN already exists. To renew, run:"
    echo "  $COMPOSE run --rm certbot renew"
    exit 0
fi

echo "==> Creating dummy certificate so nginx can start..."
$COMPOSE run --rm --entrypoint "" certbot sh -c "
    mkdir -p /etc/letsencrypt/live/$DOMAIN &&
    openssl req -x509 -nodes -newkey rsa:2048 -days 1 \
        -keyout /etc/letsencrypt/live/$DOMAIN/privkey.pem \
        -out /etc/letsencrypt/live/$DOMAIN/fullchain.pem \
        -subj '/CN=localhost'
"

echo "==> Starting nginx with dummy cert..."
$COMPOSE up -d nginx

echo "==> Removing dummy certificate..."
$COMPOSE run --rm --entrypoint "" certbot sh -c "
    rm -rf /etc/letsencrypt/live/$DOMAIN &&
    rm -rf /etc/letsencrypt/archive/$DOMAIN &&
    rm -rf /etc/letsencrypt/renewal/$DOMAIN.conf
"

echo "==> Requesting real certificate from Let's Encrypt..."
STAGING_FLAG=""
if [ "$STAGING" = "1" ]; then
    STAGING_FLAG="--staging"
    echo "    (using staging server)"
fi

$COMPOSE run --rm certbot certonly \
    --webroot \
    --webroot-path=/var/www/certbot \
    --email "$EMAIL" \
    --agree-tos \
    --no-eff-email \
    -d "$DOMAIN" \
    $STAGING_FLAG

echo "==> Reloading nginx with real certificate..."
$COMPOSE exec nginx nginx -s reload

echo ""
echo "Done! HTTPS is live at https://$DOMAIN"
echo ""
echo "To auto-renew, add this cron job:"
echo "  0 3 * * * cd $(pwd) && $COMPOSE run --rm certbot renew && $COMPOSE exec nginx nginx -s reload"
