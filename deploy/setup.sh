#!/usr/bin/env bash
# Installs StartBy on the VM the first time, and UPDATES it on every re-run
# (pull, dependencies, migrations, restart). Run as a user with sudo, not as
# root directly. See deploy/README-deploy.md for what to do BEFORE and AFTER
# (VM creation, DNS, certbot).
#
# Everything under /opt/startby is owned by www-data (the user gunicorn runs
# as), so every step that touches it runs as www-data — a plain `git pull`,
# `pip install` or `chmod` as your own user would fail with "dubious
# ownership" / "Operation not permitted" on the second run.
set -euo pipefail

APP_DIR=/opt/startby
REPO_URL="${STARTBY_REPO_URL:?Set STARTBY_REPO_URL to this repos git URL first}"
# -H: give www-data a HOME so git/pip have somewhere to put their config.
as_app() { sudo -u www-data -H "$@"; }

echo "== Installing system packages =="
sudo apt-get -o DPkg::Lock::Timeout=300 update
sudo apt-get -o DPkg::Lock::Timeout=300 install -y python3-venv python3-pip nginx certbot \
    python3-certbot-nginx git sqlite3 curl

# "First install" = no .env yet (the GCP startup script pre-clones the repo, so
# the presence of .git alone does not mean the app was ever set up).
FIRST_INSTALL=0
[ -f "$APP_DIR/.env" ] || FIRST_INSTALL=1

echo "== Fetching the code =="
sudo mkdir -p "$APP_DIR"
if [ -d "$APP_DIR/.git" ]; then
    sudo chown -R www-data:www-data "$APP_DIR"   # a pre-clone may be root-owned
    as_app git -C "$APP_DIR" pull --ff-only
else
    sudo chown www-data:www-data "$APP_DIR"
    as_app git clone "$REPO_URL" "$APP_DIR"
fi

echo "== Python virtualenv + dependencies =="
[ -d "$APP_DIR/.venv" ] || as_app python3 -m venv "$APP_DIR/.venv"
as_app "$APP_DIR/.venv/bin/pip" install --quiet --upgrade pip
as_app "$APP_DIR/.venv/bin/pip" install --quiet --no-cache-dir -r "$APP_DIR/requirements.txt"

echo "== .env =="
if [ ! -f "$APP_DIR/.env" ]; then
    # Written root-owned with umask 077 so the secrets are never world-readable,
    # then handed to www-data, which must be able to read it.
    ( umask 077
      if [ -n "${GCP_PROJECT:-}" ]; then
          # Production on GCP: settings from the template, secrets from Secret Manager.
          sed -e "s#your-project-id#${GCP_PROJECT}#g" \
              -e "s#your-domain#${DOMAIN:-localhost}#g" \
              "$APP_DIR/deploy/gcp/env.production.example" | sudo tee "$APP_DIR/.env" >/dev/null
          echo "Created .env for project ${GCP_PROJECT}; secrets load from Secret Manager."
      else
          sudo cp "$APP_DIR/.env.example" "$APP_DIR/.env"
          # A hand-made install is a production install: without this the app's
          # placeholder-secret guard (which only runs in production) never fires.
          sudo sed -i "s/^FLASK_ENV=.*/FLASK_ENV=production/;s/^BEHIND_PROXY=.*/BEHIND_PROXY=1/" \
              "$APP_DIR/.env"
          echo "!! Created .env from .env.example. Edit it with real secrets before starting. !!"
          echo "!! (FLASK_ENV=production refuses to start with placeholder secrets.)          !!"
          echo "!! Behind nginx also set BEHIND_PROXY=1, or all users share one rate limit.   !!"
      fi )
    sudo chown www-data:www-data "$APP_DIR/.env"
fi
sudo chmod 600 "$APP_DIR/.env"
sudo mkdir -p /var/log/startby
sudo chown www-data:www-data /var/log/startby

echo "== Running migrations =="
( cd "$APP_DIR" && as_app .venv/bin/python -c "from app import create_app; create_app()" )

echo "== systemd service =="
sudo cp "$APP_DIR/deploy/startby.service" /etc/systemd/system/startby.service
sudo systemctl daemon-reload
sudo systemctl enable startby

echo "== nginx =="
if [ ! -f /etc/nginx/sites-available/startby ]; then
    # First install only: later runs must NOT overwrite this file, because
    # certbot has by then rewritten it with the HTTPS block and certificate paths.
    sudo cp "$APP_DIR/deploy/nginx.conf" /etc/nginx/sites-available/startby
    if [ -n "${DOMAIN:-}" ]; then
        sudo sed -i "s/YOUR_SUBDOMAIN.duckdns.org/${DOMAIN}/g" /etc/nginx/sites-available/startby
    fi
    sudo ln -sf /etc/nginx/sites-available/startby /etc/nginx/sites-enabled/startby
    sudo rm -f /etc/nginx/sites-enabled/default
fi
sudo nginx -t

echo "== Applying the update =="
if sudo systemctl is-active --quiet startby; then
    sudo systemctl restart startby   # new code is only live after a restart
    sudo systemctl reload nginx
    # Do not report success on a service that is crash-looping (bad .env, a
    # secret that cannot be read): wait for it to actually answer.
    for _ in $(seq 1 20); do
        if curl -fs http://127.0.0.1:8000/healthz >/dev/null; then
            echo "Restarted startby and it is answering /healthz."
            break
        fi
        sleep 1
    done
    if ! curl -fs http://127.0.0.1:8000/healthz >/dev/null; then
        echo "!! startby restarted but is NOT answering. Last log lines: !!" >&2
        sudo tail -n 20 /var/log/startby/app.log >&2 || true
        exit 1
    fi
else
    echo "startby is not running yet (first install)."
fi

if [ "$FIRST_INSTALL" = 1 ]; then
    echo
    if [ -n "${GCP_PROJECT:-}" ]; then
        echo "First install done (GCP flow). Secrets live in Secret Manager, NOT in .env:"
        echo "  - SECRET_KEY, CRON_SECRET (required) and SMTP_PASSWORD, GEMINI_API_KEY (optional)"
        echo "    were created by deploy/gcp/provision.sh; $APP_DIR/.env holds only non-secret settings."
        echo "  1. Set SMTP_USER in $APP_DIR/.env to a real Gmail address (reminder emails)."
        echo "  2. Point ${DOMAIN:-your domain} at this VM's external IP (DuckDNS)."
        echo "  3. Run certbot (staging first, then the real certificate: README-deploy.md)."
        echo "  4. Start it:   sudo systemctl start startby && sudo systemctl reload nginx"
        echo "  5. Back in Cloud Shell: PHASE=after-https ./deploy/gcp/provision.sh"
        echo "  6. Optionally seed demo data (see README)."
    else
        echo "First install done. Remaining manual steps (see deploy/README-deploy.md):"
        echo "  1. Edit $APP_DIR/.env with real secrets (SECRET_KEY, CRON_SECRET, SMTP_*)."
        echo "  2. Point your DuckDNS subdomain at this VM's external IP."
        echo "  3. Run certbot (staging first!) to get the HTTPS certificate."
        echo "  4. Start it:   sudo systemctl start startby && sudo systemctl reload nginx"
        echo "  5. Optionally seed demo data (see README step 9)."
    fi
    echo
    echo "Later updates: re-run this script (it restarts the service), or"
    echo "  sudo systemctl restart startby && sudo systemctl reload nginx"
fi
