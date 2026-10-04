# 8. The 11-service GCP stack

**Status:** Accepted (2026-10-03, team decision). Supersedes the "adopt two
more, document the rest" outcome of [ADR 0007](0007-gcp-service-breadth.md).

## Context

ADR 0007 kept the architecture to a single VM and adopted only Secret
Manager and Cloud Storage beyond the original four services. The team then
finalised a larger stack because the number of distinct GCP services, each
with a real job, is a judged criterion:

Compute Engine, Cloud Scheduler, Cloud Monitoring, Cloud Logging, Secret
Manager, Cloud Storage, Vertex AI / Gemini, Pub/Sub, Cloud Tasks, BigQuery
and the Google Calendar API.

## Decision

Use all eleven, each wired to something the app actually does, and keep the
single-VM, no-client-library design:

| Service | What it does in StartBy | Code |
|---|---|---|
| Compute Engine | Runs Gunicorn + Nginx on one e2-micro | `deploy/` |
| Cloud Scheduler | `POST /api/cron/reminders` every 10 min (safety-net sweep); `POST /api/cron/backup` nightly | `deploy/gcp/provision.sh`, `app/routes/cron.py` |
| Cloud Tasks | One callback per pending task, scheduled for its `start_by`, so the start-now email goes out on the minute | `app/services/integrations.py`, `/api/internal/start-now` |
| Pub/Sub | Every task event (no titles/notes, hashed user) published to a topic for downstream consumers | `app/gcp/pubsub.py` |
| BigQuery | The same events streamed to a table to analyse estimate-vs-actual accuracy across users | `app/gcp/bigquery.py` |
| Cloud Storage | Uploaded syllabus PDFs and nightly gzip SQLite snapshots (30-day lifecycle) | `app/gcp/storage.py`, `app/services/backup_service.py` |
| Secret Manager | `SECRET_KEY`, `CRON_SECRET`, `SMTP_PASSWORD`, … loaded before config at boot; boot fails loudly if one can't be read | `app/gcp/secrets.py`, `wsgi.py` |
| Vertex AI / Gemini | Smart capture drafts tasks from pasted text/PDF (`GEMINI_BACKEND=vertex`, or the free AI Studio key) with a regex/dateparser fallback | `app/services/gemini_client.py`, `capture_service.py` |
| Cloud Logging | Structured JSON logs shipped by the Ops Agent | `app/logging_setup.py`, `deploy/gcp/startup.sh` |
| Cloud Monitoring | Uptime check on `/healthz`, an alert policy, and a custom `reminders_sent` metric | `app/gcp/monitoring.py`, `deploy/gcp/` |
| Google Calendar API | Per-user OAuth; each pending task becomes a calendar block from start-by to due; removed on complete/delete | `app/services/calendar_service.py` |

Design rules that keep this safe on a 1 GB VM:

- **REST over stdlib, no google-cloud-\* libraries.** gRPC/protobuf imports
  would cost hundreds of MB. One helper (`app/gcp/rest.py`) gives every call
  a 10 s timeout and a single retry.
- **Everything is optional and fail-safe.** An integration with blank config
  is a no-op; a Google outage is logged and dropped, never surfaced to the
  user's request. Slow calls run on a bounded background queue
  (`app/gcp/dispatcher.py`) so they can't slow requests or grow memory.
- **Events carry no personal text.** No titles or notes leave the VM; the
  user is an HMAC of their id, so BigQuery/Pub/Sub never see who or what.
- **Cloud Tasks triggers are never cancelled** — the callback re-checks the
  task, so a stale trigger (moved deadline, completed, deleted) is a harmless
  no-op, and the cron sweep remains the safety net (I7 still guarantees one
  email per task).

## Consequences — read before demoing

- **Not all of this is ₹0.** Vertex AI bills per token (the AI Studio key is
  the free path). Pub/Sub, BigQuery, Cloud Tasks, Secret Manager, Scheduler
  (3 free jobs; we use 2), Monitoring and Logging have free allowances far
  above this app's volume, but that is from the published tiers, not a bill
  we have seen — keep the budget alert from `deploy/README-deploy.md`. A
  reserved external IP is the one thing CLAUDE.md used to forbid; it is
  billed (about $3/month for an external IPv4; the new-account credit covers it),
  so release it when the VM is deleted.
- **Every service except an AI Studio key needs a billing-enabled project.**
- **Calendar needs a public HTTPS domain** for the OAuth redirect (localhost
  works for development) and, while the consent screen is in Testing mode,
  only listed test users can connect and refresh tokens expire after 7 days.
  Refresh tokens are stored in SQLite, so the DB file and its backups must
  stay private.
- **The provisioning script has not been run against a real project.** The
  integrations are covered by unit tests against faked Google endpoints, not
  by calls to real ones.
- ADR 0007's open question (Cloud Run Functions) is now closed: not adopted,
  because the single VM already runs every job.
