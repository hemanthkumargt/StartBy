# 4. Cloud Scheduler over an in-process scheduler

**Status:** Accepted

## Context

Due-date reminders (FR12) need something to trigger a check every few
minutes. The obvious alternative to an external scheduler is running a
background thread or a library like APScheduler inside the Flask process
itself.

## Decision

Use one Cloud Scheduler job (free tier allows 3 per billing account; we use
exactly one) to POST to a protected endpoint, `/api/cron/reminders`, every
5 minutes, authenticated with a shared secret header (`X-Cron-Secret`).

## Alternatives considered

- **In-process scheduler (APScheduler/a background thread)**: no external
  dependency, but Gunicorn runs 2 worker processes — an in-process scheduler
  would either run twice (double-sending reminders, which invariant I7
  explicitly forbids) or need extra coordination (a lock file, a leader
  election) to run in only one worker. That coordination is exactly the
  kind of subtle concurrency bug that is hard to get right under a four-day
  deadline, whereas Cloud Scheduler calling a single HTTP endpoint sidesteps
  the problem entirely — the endpoint itself is idempotent per task via the
  `reminders_sent` table's `UNIQUE(task_id, kind)` constraint, not via
  process coordination.
- **Cron on the VM directly (crontab)**: works, but moving the trigger out
  of the app and into GCP's own scheduler meant one less thing to configure
  by hand on the VM, and Cloud Scheduler's own dashboard shows job history
  for free, which a bare crontab entry does not.

## Consequences

- The reminder endpoint must authenticate itself (missing/wrong
  `X-Cron-Secret` → 401, sends nothing) and must be safe to call repeatedly
  or concurrently without double-sending — both are covered by tests
  (`test_I7_*`, `test_cron_rejects_*`).
- There is an external dependency (Cloud Scheduler) that must be configured
  manually once during deployment (see `deploy/README-deploy.md` §7); if
  it's ever disabled or misconfigured, reminders simply stop firing with no
  in-app symptom — the uptime check is on `/healthz`, not on reminder
  delivery, which is a known gap for a future iteration.
