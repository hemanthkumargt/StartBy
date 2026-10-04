# Deploying StartBy to Compute Engine

Everything here stays within the free tier (plus one small, known charge: the
static IP, below) as long as you follow it exactly. Read the whole page before
starting — several steps (billing alert, certbot staging) exist specifically to
stop you from accidentally spending money or getting rate-limited.

There are two ways to deploy:

* **Primary: `deploy/gcp/provision.sh`** — one script creates every Google Cloud
  resource (VM, static IP, firewall, bucket, Pub/Sub, BigQuery, Cloud Tasks,
  secrets, Scheduler, uptime check). Follow "The dry-run order" next.
* **Fallback: the manual / console flow** ("Manual flow" further down) — the same
  result by hand in the console, for when the script fails on your gcloud version
  or you want to understand each piece.

> The script has **not been run against a real project yet**. Treat the first run
> as a dry run: read its output, and expect to adjust a flag or two.

## The dry-run order

Do these in order. Each step assumes the previous one is finished.

1. **Commit, merge, push.** The VM clones `STARTBY_REPO_URL` anonymously over
   https, so everything you want deployed must be on `main` of a *public* repo
   (or swap in a deploy token). Run the test suite first.
2. **Billing + budget alert.** Link billing to the project (several APIs refuse
   otherwise) and create a budget alert (section 1 below) *before* creating anything.
3. **Open Cloud Shell** (console.cloud.google.com, the `>_` icon): gcloud is already
   logged in as you. `gcloud config set project <PROJECT_ID>`.
4. **Run `provision.sh`** (phase 1, the default run — infrastructure only):
   ```bash
   git clone https://github.com/<you>/StartBy.git && cd StartBy
   PROJECT_ID=my-project DOMAIN=startby.duckdns.org \
     STARTBY_REPO_URL=https://github.com/<you>/StartBy.git \
     SMTP_PASSWORD=<gmail app password> GEMINI_API_KEY=<AI Studio key> \
     ./deploy/gcp/provision.sh
   ```
   `SMTP_PASSWORD`, `GEMINI_API_KEY` and `GOOGLE_CLIENT_SECRET` are optional: a
   secret that does not exist is skipped at boot with a warning and its feature
   stays off. `SECRET_KEY` and `CRON_SECRET` are generated for you and are required.
   It ends by printing the exact next steps and the VM's IP.
5. **DNS.** Point your DuckDNS subdomain at the printed static IP.
6. **certbot** on the VM (wait ~3-5 minutes after step 4 for the startup script to
   install the app; `gcloud compute ssh startby-vm --zone us-central1-a`). Staging
   first, then the real certificate — see "Staging to real certificate" below.
7. **Start the service:** `sudo systemctl start startby && sudo systemctl reload nginx`
   (check `sudo systemctl status startby` and `curl -fsS https://<domain>/healthz`).
   Only now set `SECURE_COOKIES=1` in `/opt/startby/.env` and restart.
8. **Phase 2 of the script** (needs the live HTTPS site: uptime check, alert policy,
   the two Cloud Scheduler jobs):
   ```bash
   PHASE=after-https PROJECT_ID=my-project DOMAIN=startby.duckdns.org \
     STARTBY_REPO_URL=https://github.com/<you>/StartBy.git ./deploy/gcp/provision.sh
   ```
   (It also runs by itself if you re-run the script once `/healthz` answers.)
   Add your email as a notification channel on the alert policy (Monitoring >
   Alerting) — as created it fires but emails nobody.
9. **Seed** demo data (section 9 below).
10. **Rehearse** backup, restore and rollback once before the demo (sections
    "Rollback" and "Backups and restore" below). A procedure never tried is a guess.

### Staging to real certificate

Let's Encrypt rate-limits real issuance, so rehearse with `--staging` first. A
staging certificate is **not trusted** by browsers, and certbot will not replace it
with a real one just because you run the normal command again. After staging works:

```bash
sudo certbot delete --cert-name YOUR_DOMAIN                 # remove the staging lineage
sudo certbot --nginx -d YOUR_DOMAIN                         # issue the real certificate
# or, instead of delete: sudo certbot --nginx -d YOUR_DOMAIN --force-renewal
```

Do **not** set `SECURE_COOKIES=1` (or expect HSTS to be safe) until the real
certificate is installed and `https://YOUR_DOMAIN` loads without a browser warning:
a Secure cookie is never sent over plain `http://`, so turning it on early makes
login impossible.

### Cost note: the static IP is billed

The reserved static IP (`startby-vm-ip`) is billed — about $3/month for an external
IPv4 address. A new account's free credit covers it, so expect no charge during the
hackathon, but it is **not** free-tier. If you delete the VM, delete the address too:
`gcloud compute addresses delete startby-vm-ip --region us-central1`.

### Rotating a secret

Secrets are read from Secret Manager once, at service start.

```bash
# 1. add a new version (never edit the old one)
printf '%s' "$(python3 -c 'import secrets; print(secrets.token_hex(32))')" | \
  gcloud secrets versions add CRON_SECRET --data-file=-
# 2. on the VM, restart so both workers re-read it
sudo systemctl restart startby
# 3. CRON_SECRET only: both Cloud Scheduler jobs hold a copy in their headers
SECRET="$(gcloud secrets versions access latest --secret CRON_SECRET)"
for job in startby-reminders startby-backup; do
  gcloud scheduler jobs update http "$job" --location us-central1 \
    --update-headers "X-Cron-Secret=$SECRET"
done
```

Notes: rotating `SECRET_KEY` signs everyone out (expected). Cloud Tasks already queued
for start-now reminders carry the *old* `CRON_SECRET` in their headers and will be
rejected with 401 until they exhaust their retries (the queue allows 10 attempts with
backoff up to 10 minutes, so roughly 40 minutes); the 10-minute Scheduler sweep sends any
reminder those tasks would have, so nothing is lost, only delayed. Rotate when the
queue is quiet if you can.

### Known limits

* Reminders are **at-most-once**: a reminder is claimed before it is sent, and a
  crash between claim and send loses that one (failed sends are released and retried).
* Emails per sweep are limited by SMTP latency: roughly **7-14 per 10-minute run**
  (each send takes 1-3 s inside a 20 s run budget). A burst of due tasks across many
  users drains over several sweeps.
* While the Google OAuth consent screen is in **Testing** mode, Calendar refresh
  tokens **expire after 7 days** (users simply reconnect), and only listed test
  users can connect.
* **BigQuery streaming inserts need billing** enabled on the project; without it the
  event stream is dropped (logged) and the rest of the app is unaffected.
* Queued background jobs (events, Calendar sync) are in memory; a graceful restart
  waits up to 8 s to finish them, a crash or `kill -9` loses them.

---

# Manual flow (fallback)

The same deployment by hand. Use this if `provision.sh` fails or you want to see each
piece. (With the script, steps 2, 4, 5 and 7 below are already done for you.)

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
`FEATURE_*` default to off in `.env.example`; switch on the ones you want
(`FEATURE_ESTIMATES`, `FEATURE_SMART_CAPTURE`, `FEATURE_INSIGHTS`). The app
refuses to start with `FLASK_ENV=production` while `SECRET_KEY`/`CRON_SECRET`
are missing, short, or still a placeholder.

**Also set these two for a normal nginx deploy** (they are in
`deploy/gcp/env.production.example` but easy to miss when editing by hand):

- `BEHIND_PROXY=1` — without it every visitor looks like `127.0.0.1` to the app,
  so the login/sign-up rate limits apply to the *whole site at once*.
- `SECURE_COOKIES=1` — only after the **real** certificate is installed (step 6); a
  Secure cookie is never sent over plain `http://`, so turning it on early makes
  logging in impossible. Leave it `0` for now.

Then:

```bash
sudo systemctl start startby
sudo systemctl status startby   # should show "active (running)"
```

## 6. DNS + HTTPS

1. Create a free subdomain at [duckdns.org](https://www.duckdns.org) pointing
   at the VM's external IP.
2. If you did not export `DOMAIN` before `setup.sh`, edit
   `/etc/nginx/sites-available/startby` and replace
   `YOUR_SUBDOMAIN.duckdns.org` with your real one. The shipped config is
   HTTP-only on purpose: certbot adds the 443 block and the redirect itself.
3. **Test with staging first** — Let's Encrypt rate-limits repeated real
   issuance per domain per week, and a typo will burn an attempt:
   ```bash
   sudo certbot --nginx --staging -d YOUR_SUBDOMAIN.duckdns.org
   ```
   If that succeeds without errors, switch to the real certificate (the staging one
   is not trusted and certbot will not replace it by itself):
   ```bash
   sudo certbot delete --cert-name YOUR_SUBDOMAIN.duckdns.org
   sudo certbot --nginx -d YOUR_SUBDOMAIN.duckdns.org
   # or: sudo certbot --nginx -d YOUR_SUBDOMAIN.duckdns.org --force-renewal
   ```
   Certbot edits the Nginx config in place to point at the real cert and
   sets up auto-renewal (`certbot renew` via a systemd timer it installs).
   Once the REAL certificate works, set `SECURE_COOKIES=1` in `.env` and restart the
   service (a Secure cookie is never sent over plain HTTP, so do this last).
4. `sudo nginx -t && sudo systemctl reload nginx`
5. Visit `https://YOUR_SUBDOMAIN.duckdns.org` — should load over HTTPS, and
   plain `http://` should redirect to it.

## 7. Cloud Scheduler — two jobs

Cloud Scheduler → Create Job (or let `deploy/gcp/provision.sh` do it):

| Job | Frequency | URL (POST) |
|---|---|---|
| reminders (safety-net sweep) | `*/10 * * * *` | `https://YOUR_SUBDOMAIN.duckdns.org/api/cron/reminders` |
| nightly backup | `30 2 * * *` | `https://YOUR_SUBDOMAIN.duckdns.org/api/cron/backup` |

Both need the header `X-Cron-Secret: <your CRON_SECRET>`. Billing accounts
get 3 free Cloud Scheduler jobs total — this app uses two; check the quota
before adding a third. (Start-now reminders also fire at their exact time via
Cloud Tasks when `CLOUD_TASKS_QUEUE` is configured; the sweep is the net
under that.)

## 8. Uptime check (Cloud Monitoring)

Cloud Monitoring → Uptime checks → Create:

- **Protocol**: HTTPS
- **Hostname**: your DuckDNS subdomain
- **Path**: `/healthz`
- Alert on failure (email is enough for a hackathon).

## 9. Seed demo data

On a production install the seed script refuses the placeholder password, because
the demo account would otherwise be a public login on the live site. Put a real one
in `/opt/startby/.env` first (12+ characters, not `change-me`):

```bash
echo 'SEED_USER_PASSWORD=<a-long-unguessable-password>' | sudo tee -a /opt/startby/.env
cd /opt/startby
sudo -u www-data .venv/bin/python scripts/seed.py     # prints which database it is touching
```

The demo login page autofills `demo@startby.local` / `change-me`; with a real password
set, share that password with the judges instead. Everyone behind one network address
shares one login-attempt budget (20 wrong tries per account, 150 per address, per 5
minutes), so give each judge their own account if you can.

Run it with `--reset` right before the actual demo to get clean, predictable
data (`scripts/seed.py --reset`).

## Cost traps (re-read this before changing anything)

- Never change the VM's region or machine type — only `us-central1` /
  `us-west1` / `us-east1` + `e2-micro` is Always Free.
- No load balancer, Cloud SQL instance, or Cloud Function. One static IP is
  reserved for the VM (a changing IP would break DNS). It is **billed**, about
  $3/month (the new-account credit covers it), so release it if you delete the VM.
- Keep Cloud Scheduler at 3 jobs or fewer (we use 2).
- Gemini defaults to a free Google AI Studio key (`GEMINI_BACKEND=ai_studio`).
  The Vertex AI backend is billed per token — opt in only on purpose.

## Logs

The service writes to `/var/log/startby/app.log` (JSON when `LOG_FORMAT=json`);
the Ops Agent ships that file to Cloud Logging and logrotate trims it. Use
`sudo tail -f /var/log/startby/app.log`, not `journalctl -u startby`.

## Updating the app

`setup.sh` is safe to re-run (export `STARTBY_REPO_URL` first — it aborts without it):
it pulls as `www-data` (the tree is owned by that
user, so a plain `git pull` as yourself fails with "dubious ownership"),
reinstalls dependencies and restarts the service.

## Rollback

Roll back to a known-good commit (create tags with `git tag v1.0 <sha>` and push
them first if you want names instead of SHAs). The tree belongs to `www-data`, so
run git as that user, and return to `main` afterwards or the next `setup.sh`
update fails with "You are not currently on a branch":

```bash
cd /opt/startby
sudo systemctl stop startby
sudo -u www-data git checkout <sha-or-tag>
# restore the matching DB backup: see "Backups and restore" below (do not just cp over a live WAL database)
sudo systemctl start startby
```

### Backups and restore (read before you need them)

The database runs in WAL mode, so the data lives in `app.db` **and** the
`app.db-wal` / `app.db-shm` files beside it. A plain `cp app.db …` while the app
is running misses whatever is still in the `-wal` file, and copying an old
`app.db` back next to a *newer* `-wal` can corrupt it. Use SQLite's own backup:

```bash
# Safe while the app is running:
sudo -u www-data mkdir -p /opt/startby/backups
sudo -u www-data sqlite3 /opt/startby/instance/app.db \
  ".backup /opt/startby/backups/app-$(date +%Y%m%d-%H%M).db"
```

Nightly backups also go to Cloud Storage (`backups/startby-<time>.db.gz`, Google
Calendar tokens blanked — users reconnect Calendar after a restore). To restore
one:

```bash
sudo systemctl stop startby
cd /opt/startby/instance
sudo -u www-data rm -f app.db app.db-wal app.db-shm        # stale WAL files must go
gcloud storage cp gs://<bucket>/backups/startby-<time>.db.gz /tmp/restore.db.gz
gunzip -c /tmp/restore.db.gz | sudo -u www-data tee app.db >/dev/null
sudo -u www-data /opt/startby/.venv/bin/python -c \
  "import sqlite3; print(sqlite3.connect('app.db').execute('PRAGMA integrity_check').fetchone()[0])"
# must print: ok   (setup.sh also installs the sqlite3 command-line tool)
sudo systemctl start startby
```

After restoring an OLDER backup, also change `SECRET_KEY` (that signs every session
cookie): old cookies hold user ids that may now belong to different people.

Do a trial restore into a scratch folder once before the demo, so the procedure
is known to work.

## Troubleshooting

- `sudo systemctl status startby` / `sudo tail -n 50 /var/log/startby/app.log` — app
  logs (structured single-line logs; cron runs and 5xx errors are logged
  here).
- `sudo nginx -t` — validates the Nginx config before reloading.
- If the service won't start, check `/opt/startby/.env` exists and is
  readable by `www-data` (a missing `EnvironmentFile` fails the unit — that shows up in
  `sudo journalctl -u startby -n 30`, not in `app.log`, because the app never started).
  A service that restarts every 3 seconds is almost always a bad `.env` or an
  unreadable Secret Manager secret; `setup.sh` now waits for `/healthz` and prints the
  last log lines if it never answers. A missing *optional* secret (SMTP_PASSWORD,
  GEMINI_API_KEY) no longer stops the app: it is logged as `optional_secret_skipped`
  and that feature stays off; a missing `SECRET_KEY` or `CRON_SECRET` fails loudly.


## Google Cloud integrations (optional, all 11 services)

`deploy/gcp/provision.sh` creates the service account, bucket (30-day backup
expiry), Pub/Sub topic, BigQuery dataset + table, Cloud Tasks queue, secrets,
static IP, firewall rule, the e2-micro VM, the two Cloud Scheduler jobs and
the uptime check/alert. Read it first — it has **not been run against a real
project**, so treat the first run as a dry run. It is the primary path; see "The
dry-run order" at the top of this page.

```bash
PROJECT_ID=my-project DOMAIN=startby.duckdns.org \
  STARTBY_REPO_URL=https://github.com/<you>/StartBy.git \
  SMTP_PASSWORD=... ./deploy/gcp/provision.sh                 # phase 1: infrastructure
PHASE=after-https PROJECT_ID=... DOMAIN=... STARTBY_REPO_URL=... \
  ./deploy/gcp/provision.sh                                   # phase 2: uptime, alert, Scheduler
```

Then copy `deploy/gcp/env.production.example` into `/opt/startby/.env` on the
VM (secrets stay in Secret Manager; `GCP_SECRETS` lists which to load).

Things that will bite if skipped:

* Billing must be linked, and the budget alert from step 1 should exist
  first — Vertex AI, BigQuery and Pub/Sub are free only below their tiers.
* Cloud Scheduler and Cloud Tasks call back into the app, so they need a public HTTPS URL, so
  DNS + certbot (steps 5–6) come before the scheduler jobs can succeed.
* Google Calendar needs an OAuth web client with the redirect URI
  `https://<domain>/calendar/callback`; in Testing mode only listed test users
  can connect and refresh tokens last 7 days.
* The static IP is billed (about $3/month; the new-account credit covers it), and
  more if left unattached — never delete the VM and leave the address reserved.
