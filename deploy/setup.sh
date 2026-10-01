#!/usr/bin/env bash
# Idempotent VM setup: safe to re-run if the VM needs to be rebuilt quickly.
# Run as a user with sudo (not as root directly). See deploy/README-deploy.md
# for what to do BEFORE and AFTER this script (VM creation, DNS, certbot).
set -euo pipefail

APP_DIR=/opt/startby
REPO_URL="${STARTBY_REPO_URL:?Set STARTBY_REPO_URL to this repos git URL first}"

echo "== Installing system packages =="
sudo apt-get update
sudo apt-get install -y python3-venv python3-pip nginx certbot python3-certbot-nginx git

echo "== Cloning / updating the repo =="
if [ ! -d "$APP_DIR/.git" ]; then
    sudo mkdir -p "$APP_DIR"
    sudo chown "$USER:$USER" "$APP_DIR"
    git clone "$REPO_URL" "$APP_DIR"
else
    git -C "$APP_DIR" pull --ff-only
fi

echo "== Python virtualenv + dependencies =="
cd "$APP_DIR"
python3 -m venv .venv
. .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

echo "== .env =="
if [ ! -f "$APP_DIR/.env" ]; then
    cp "$APP_DIR/.env.example" "$APP_DIR/.env"
    echo "!! Created .env from .env.example — edit it with real secrets before starting the service !!"
fi

echo "== Running migrations =="
python -c "from app import create_app; create_app()"

echo "== Permissions (Gunicorn runs as www-data) =="
sudo chown -R www-data:www-data "$APP_DIR"

echo "== systemd service =="
sudo cp "$APP_DIR/deploy/startby.service" /etc/systemd/system/startby.service
sudo systemctl daemon-reload
sudo systemctl enable startby

echo "== nginx (HTTP only for now — run certbot before enabling HTTPS) =="
sudo cp "$APP_DIR/deploy/nginx.conf" /etc/nginx/sites-available/startby
sudo ln -sf /etc/nginx/sites-available/startby /etc/nginx/sites-enabled/startby
sudo rm -f /etc/nginx/sites-enabled/default

echo
echo "Setup done. Remaining manual steps (see deploy/README-deploy.md):"
echo "  1. Edit $APP_DIR/.env with real secrets (SECRET_KEY, CRON_SECRET, SMTP_*)."
echo "  2. Point your DuckDNS subdomain at this VM external IP."
echo "  3. Run certbot (staging first!) to get the HTTPS certificate."
echo "  4. sudo systemctl start startby && sudo systemctl reload nginx"
echo "  5. Optionally: .venv/bin/python scripts/seed.py"
