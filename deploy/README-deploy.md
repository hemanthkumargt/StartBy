# Deploying StartBy to Compute Engine

Everything here costs ₹0 as long as you follow it exactly. Read the whole
page before starting — several steps (billing alert, certbot staging) exist
specifically to stop you from accidentally spending money or getting
rate-limited.

## 1. Before you touch the console: set a budget alert

GCP Console → Billing → Budgets & alerts → Create budget. Set it to the
smallest amount the console allows (e.g. ₹1) with email alerts at 50/90/100%.
Do this **first** — Compute Engine's Always Free tier covers everything
below, but a budget alert is your safety net if a step goes wrong.

## 2. Create the VM

Compute Engine → VM instances → Create instance:

- **Region**: `us-central1` (or `us-west1` / `us-east1` — Always Free only
  applies to these three). Any other region bills you.
- **Machine type**: `e2-micro`.
- **Boot disk**: Ubuntu 22.04 LTS, 30 GB standard persistent disk.
- **Firewall**: check "Allow HTTP traffic" and "Allow HTTPS traffic".
- Leave everything else default.

Note the VM's external IP once it's created.

## 3. Connect

```bash
gcloud compute ssh startby-vm --zone us-central1-a
```

If campus/hostel Wi-Fi blocks outbound port 22 (common), use the **SSH
button directly in the GCP Console** instead — it tunnels over HTTPS and
works from any network.

## 4. Run the setup script

```bash
export STARTBY_REPO_URL=https://github.com/<your-org>/startby.git
curl -fsSL https://raw.githubusercontent.com/<your-org>/startby/main/deploy/setup.sh | bash
```

(Or clone the repo first and run `bash deploy/setup.sh` locally on the VM —
safer if you want to read it before running it. The script is idempotent:
re-running it after editing code just pulls and restarts cleanly.)

It installs Python/Nginx/certbot, clones the repo to `/opt/startby`, creates
a venv, runs migrations, installs the systemd service, and installs the
Nginx config (HTTP-only at this point — HTTPS comes in step 6).

## 5. Fill in real secrets

```bash
sudo nano /opt/startby/.env
```

Set `SECRET_KEY` (any long random string), `CRON_SECRET` (another random
string — Cloud Scheduler will send this back to you in step 7), and
`SMTP_USER` / `SMTP_PASSWORD` (a Gmail address + an **app password**, not
your real password — generate one at myaccount.google.com/apppasswords).
Leave `GEMINI_*` and `FEATURE_*` alone; they're Phase 2.

Then:

```bash
sudo systemctl start startby
sudo systemctl status startby   # should show "active (running)"
```

## 6. DNS + HTTPS

1. Create a free subdomain at [duckdns.org](https://www.duckdns.org) pointing
   at the VM's external IP.
2. Edit `/etc/nginx/sites-available/startby` and replace
   `YOUR_SUBDOMAIN.duckdns.org` with your real one (both server blocks).
3. **Test with staging first** — Let's Encrypt rate-limits repeated real
   issuance per domain per week, and a typo will burn an attempt:
   ```bash
   sudo certbot --nginx --staging -d YOUR_SUBDOMAIN.duckdns.org
   ```
   If that succeeds without errors, get the real certificate:
   ```bash
   sudo certbot --nginx -d YOUR_SUBDOMAIN.duckdns.org
   ```
   Certbot edits the Nginx config in place to point at the real cert and
   sets up auto-renewal (`certbot renew` via a systemd timer it installs).
4. `sudo nginx -t && sudo systemctl reload nginx`
5. Visit `https://YOUR_SUBDOMAIN.duckdns.org` — should load over HTTPS, and
   plain `http://` should redirect to it.

## 7. Cloud Scheduler (reminders) — exactly ONE job

Cloud Scheduler → Create Job:

- **Frequency**: `*/5 * * * *` (every 5 minutes)
- **Target type**: HTTP
- **URL**: `https://YOUR_SUBDOMAIN.duckdns.org/api/cron/reminders`
- **HTTP method**: POST
- **Headers**: `X-Cron-Secret: <the CRON_SECRET you put in .env>`

Billing accounts get 3 free Cloud Scheduler jobs total — this app uses
exactly one. Don't create a second one for anything else without checking
the free quota first.

## 8. Uptime check (Cloud Monitoring)

Cloud Monitoring → Uptime checks → Create:

- **Protocol**: HTTPS
- **Hostname**: your DuckDNS subdomain
- **Path**: `/healthz`
- Alert on failure (email is enough for a hackathon).

## 9. Seed demo data

```bash
cd /opt/startby
sudo -u www-data .venv/bin/python scripts/seed.py
```

Run it with `--reset` right before the actual demo to get clean, predictable
data (`scripts/seed.py --reset`).

## Cost traps (re-read this before changing anything)

- Never change the VM's region or machine type — only `us-central1` /
  `us-west1` / `us-east1` + `e2-micro` is Always Free.
- Never add a static IP, load balancer, Cloud SQL instance, or Cloud
  Function — none of these are in the Always Free tier.
- Never create a second Cloud Scheduler job without checking you're still
  under the 3-per-account free quota.
- Gemini (Phase 2) must use a free Google AI Studio key only — never attach
  a billing account to that project.

## Rollback

Every Phase 1 milestone is a git tag (`v1.0` after S4, `v1.1` after S6).
To roll back:

```bash
cd /opt/startby
sudo systemctl stop startby
git checkout <tag>                       # e.g. v1.0
cp backups/app-<date>.db instance/app.db # restore the matching DB backup
sudo systemctl start startby
```

Always back up the database before a migration or a risky deploy:

```bash
mkdir -p backups
cp /opt/startby/instance/app.db backups/app-$(date +%Y%m%d-%H%M).db
```

## Troubleshooting

- `sudo systemctl status startby` / `sudo journalctl -u startby -n 50` — app
  logs (structured single-line logs; cron runs and 5xx errors are logged
  here).
- `sudo nginx -t` — validates the Nginx config before reloading.
- If the service won't start, check `/opt/startby/.env` exists and is
  readable by `www-data` — `EnvironmentFile` in the systemd unit silently
  skips a missing file, so the app would start with insecure defaults
  (including `SECRET_KEY`) rather than failing loudly.
