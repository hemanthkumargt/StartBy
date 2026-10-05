# Cloud 6 — PRD Phase 1 (Use Case 1 Baseline)

Oct 1, 2026 · @Hk

## How to use this doc

Build ONLY what this document specifies: the Use Case 1 baseline from the NPN GCP Hackathon brief (Cognizant). This is Phase 1. Phase 2 features must NOT be started until sprint S5, after Phase 1 is tagged v1.0. Follow the Implementation plan at the end, one sprint at a time.

Instructions for Claude Code:

1. Read the whole PRD before writing code. Ask questions if anything is ambiguous.
2. Work in the order of the Build plan in the Project structure section. Commit after each step.
3. Keep the code clean and readable: judges grade "clean code" and "architecture".
4. Do not add libraries, services or features beyond this PRD without asking.
5. Respect the extension points described below, so Phase 2 can plug in without rewrites.
6. Everything must run at zero cost (see Constraints).

## Overview

Cloud 6 is a task manager web app where users add, edit, complete and delete tasks, deployed on a single Google Compute Engine Linux VM. Phase 1 delivers every item in the hackathon brief, polished and demo-ready.

**Goals**

- Full task CRUD with persistence that survives page refresh and server restart.
- All six brief features: due date reminders, tags, dark mode, task counter, activity log, responsive design.
- Deployed on Compute Engine with Gunicorn under systemd behind Nginx, on ports 80 and 443.
- A clean homepage with status badges and counts, so the app looks finished.

**Non-goals (Phase 1)**

- No AI features, no time estimates, no start-by logic, no risk colours.
- No Cloud SQL, no Docker, no Kubernetes, no React build step.
- No team or shared tasks.

## Tech stack and constraints

The stack follows the brief exactly and costs ₹0.

| Layer | Choice | Notes |
| --- | --- | --- |
| Backend | Python 3.11+, Flask, Flask-Login | App factory + blueprints |
| Frontend | Jinja2 templates + vanilla JS + CSS | No framework, no build step; JS calls the JSON API with fetch |
| Database | SQLite via Python sqlite3 | WAL mode on; SQL migrations in a folder |
| Server | Gunicorn (2 workers) under systemd, behind Nginx | e2-micro has 1 GB RAM |
| VM | Compute Engine e2-micro, Ubuntu 22.04 LTS | Region us-central1 (Always Free) |
| HTTPS | Let's Encrypt via certbot, free DuckDNS subdomain | Port 443 actually used |
| Reminders | Cloud Scheduler (1 job) calls a protected endpoint every 5 min | Email via Gmail SMTP app password |
| Tests | pytest | API-level tests for CRUD |

**Hard constraints**

- Zero cost: only Always Free resources. Region must be us-west1, us-central1 or us-east1.
- All secrets (SECRET\_KEY, SMTP password, CRON\_SECRET) come from a `.env` file, never committed. Provide `.env.example`.
- All datetimes stored in UTC as ISO 8601 strings; displayed in the user's timezone (default Asia/Kolkata).
- Passwords hashed with Werkzeug `generate_password_hash`.
- CSRF protection on form posts; parameterised SQL only.

## Functional requirements

Each requirement maps to a line in the hackathon brief.

| ID | Requirement | Behaviour |
| --- | --- | --- |
| FR1 | Auth | Register, login, logout. Each user sees only their own tasks. |
| FR2 | Add task | Form with title (required, max 200 chars), notes (optional), tag, due date and time (optional). |
| FR3 | List tasks | Shows pending tasks first, sorted by due date ascending (no due date last), then done tasks. Filter by status and tag; search by title. |
| FR4 | Edit task | Edit modal prefilled with current values; saves without full page reload. |
| FR5 | Complete / reopen | Checkbox toggles status between pending and done; sets or clears completed\_at. |
| FR6 | Delete task | Delete button with a confirm dialog. Soft delete (deleted\_at set); deleted tasks never appear in lists or counts. |
| FR7 | Status badges | Pending, Done, and Overdue (pending and due date in the past). Overdue is computed, not stored. |
| FR8 | Tags | Fixed set: work, study, personal. Coloured chips, filter bar on the list page. |
| FR9 | Task counter | Total, completed, pending and overdue counts on the homepage; update live after any change. |
| FR10 | Activity log | Every create, update (per changed field), complete, reopen and delete writes a row. A timeline page shows newest first with old and new values. |
| FR11 | Dark mode | Toggle in the header. Colours are CSS variables. Choice saved to the user record and applied on load with no flash. |
| FR12 | Due date reminders | Email "due within 24 hours" and "overdue" reminders. Each kind is sent at most once per task. Triggered by Cloud Scheduler calling the cron endpoint. |
| FR13 | Responsive design | Mobile-first. Works from 360 px wide; cards stack on phones, grid on desktop. Touch targets at least 44 px. |
| FR14 | Clean homepage | Dashboard with counters, the next few tasks due, and a quick-add form. |
| FR15 | Health check | GET /healthz returns 200 with JSON status and DB check, for uptime monitoring. |

## Data model

Four app tables plus a migrations table, created by `migrations/001_init.sql`. Phase 2 adds columns through new numbered migration files, never by editing 001.

```sql
PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;

CREATE TABLE schema_migrations (
  version    TEXT PRIMARY KEY,
  applied_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE users (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  name          TEXT NOT NULL,
  email         TEXT NOT NULL UNIQUE,
  password_hash TEXT NOT NULL,
  timezone      TEXT NOT NULL DEFAULT 'Asia/Kolkata',
  dark_mode     INTEGER NOT NULL DEFAULT 0,
  created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE tasks (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id      INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  title        TEXT NOT NULL,
  notes        TEXT,
  tag          TEXT NOT NULL DEFAULT 'personal'
               CHECK (tag IN ('work','study','personal')),
  status       TEXT NOT NULL DEFAULT 'pending'
               CHECK (status IN ('pending','done')),
  due_at       TEXT,
  created_at   TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at   TEXT NOT NULL DEFAULT (datetime('now')),
  completed_at TEXT,
  deleted_at   TEXT
);
CREATE INDEX idx_tasks_user_status_due ON tasks(user_id, status, due_at);
CREATE INDEX idx_tasks_due ON tasks(status, due_at);

CREATE TABLE activity_log (
  id        INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id   INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  task_id   INTEGER REFERENCES tasks(id) ON DELETE SET NULL,
  action    TEXT NOT NULL CHECK (action IN
            ('created','updated','completed','reopened','deleted')),
  field     TEXT,
  old_value TEXT,
  new_value TEXT,
  at        TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX idx_activity_user_at ON activity_log(user_id, at DESC);

CREATE TABLE reminders_sent (
  id      INTEGER PRIMARY KEY AUTOINCREMENT,
  task_id INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
  kind    TEXT NOT NULL CHECK (kind IN ('due_soon','overdue')),
  sent_at TEXT NOT NULL DEFAULT (datetime('now')),
  UNIQUE (task_id, kind)
);
```

Note: SQLite CHECK constraints cannot be altered in place. Phase 2 will add new tags and reminder kinds, so keep the allowed values also as Python constants in `app/constants.py`, and have the migration runner support table rebuilds.

## API contract

All JSON endpoints live under `/api`, require login (except auth and health), and return errors as `{"error": {"code": "...", "message": "..."}}` with the right HTTP status.

| Method | Path | Purpose | Success |
| --- | --- | --- | --- |
| POST | /api/auth/register | Create account; body: name, email, password | 201 |
| POST | /api/auth/login | Log in; body: email, password | 200 |
| POST | /api/auth/logout | Log out | 204 |
| GET | /api/tasks | List; query: status, tag, q | 200, array of tasks |
| POST | /api/tasks | Create; body: title, notes, tag, due\_at | 201, task |
| GET | /api/tasks/:id | Fetch one | 200, task |
| PATCH | /api/tasks/:id | Partial update of title, notes, tag, due\_at | 200, task |
| POST | /api/tasks/:id/complete | Mark done | 200, task |
| POST | /api/tasks/:id/reopen | Mark pending | 200, task |
| DELETE | /api/tasks/:id | Soft delete | 204 |
| GET | /api/dashboard | Counts (total, completed, pending, overdue) + next 5 due | 200 |
| GET | /api/activity | Activity log; query: limit (default 50), before | 200 |
| PATCH | /api/me | Update settings (dark\_mode, timezone) | 200 |
| POST | /api/cron/reminders | Send due-soon and overdue emails; requires header `X-Cron-Secret` | 200, counts sent |
| GET | /healthz | Liveness + DB check | 200 |

Task JSON shape: `id, title, notes, tag, status, due_at, is_overdue, created_at, updated_at, completed_at`. `is_overdue` is computed in the service layer.

Validation: unknown tag → 422; empty title → 422; another user's task → 404 (never 403, to avoid leaking IDs); bad cron secret → 401.

## UI pages

Server-rendered page shells (Jinja2); all data loads and changes go through the JSON API with fetch, so actions never reload the page.

| Page | Route | Contents |
| --- | --- | --- |
| Login / Register | /login, /register | Simple centred forms, inline validation errors |
| Homepage (dashboard) | / | Four counter cards (total, completed, pending, overdue), quick-add form, "Due next" list of 5 |
| Tasks | /tasks | Status tabs (All, Pending, Done), tag filter chips, search box, task cards with badge, tag chip, due date, complete checkbox, edit and delete buttons |
| Edit modal | (on /tasks) | Prefilled form; Save and Cancel; Esc closes; focus trapped while open |
| Activity | /activity | Timeline, newest first: "Edited 'DBMS report': due 3 Oct → 5 Oct", relative times |
| Settings | /settings | Dark mode toggle, timezone select |

**Design rules**

- One shared header: app name, nav links, dark mode toggle, logout.
- Colours only from CSS variables in `static/css/theme.css`, with light and dark sets.
- Tag colours: work = blue, study = purple, personal = green. Badge colours: pending = amber, done = green, overdue = red. Always pair colour with a text label.
- Empty states for no tasks and no activity, with a call to action.
- Toast messages for success and error; show a loading state on buttons during requests.

## Project structure and extension points

Layered design: routes handle HTTP only, services hold business logic, repositories hold SQL. Phase 2 adds new services and routes without rewriting Phase 1 code.

```
startby/
├── app/
│   ├── __init__.py          # create_app() factory, registers blueprints
│   ├── config.py            # loads .env
│   ├── constants.py         # TAGS, STATUSES, REMINDER_KINDS
│   ├── db.py                # connection per request, migration runner
│   ├── routes/              # blueprints: auth, tasks, dashboard, activity, settings, cron, pages, health
│   ├── services/
│   │   ├── task_service.py      # CRUD rules, is_overdue, calls activity_service
│   │   ├── activity_service.py  # write + read activity log
│   │   ├── reminder_service.py  # find due tasks, send, record
│   │   ├── notifier.py          # Notifier interface + SmtpNotifier
│   │   └── hooks.py             # task event hooks (empty in Phase 1)
│   ├── repositories/        # task_repo.py, user_repo.py, activity_repo.py, reminder_repo.py
│   ├── templates/           # base.html + one template per page
│   └── static/              # css/theme.css, css/app.css, js/api.js, js/tasks.js, ...
├── migrations/001_init.sql
├── scripts/seed.py          # demo user + ~30 realistic tasks across tags and dates
├── deploy/                  # nginx.conf, startby.service (systemd), setup.sh
├── tests/                   # pytest: CRUD, auth isolation, activity log, reminders
├── .env.example
├── requirements.txt
├── wsgi.py
└── README.md                # local run, deploy steps, architecture diagram
```

**Extension points (build these hooks now, keep them empty)**

- `hooks.py` exposes `on_task_created`, `on_task_updated`, `on_task_completed`. task\_service calls them after each write. Phase 2 plugs estimate tracking in here.
- task\_service builds the task JSON in one function (`serialize_task`). Phase 2 adds computed fields (start\_by, risk) there only.
- reminder\_service decides which reminders to send through a list of rule functions. Phase 2 appends a "start now" rule.
- Notifier is an interface so the channel can change later without touching reminder logic.
- The frontend renders task cards from one function in `tasks.js`, so new badges slot in one place.

**Build plan (commit after each step)**

1. Scaffold, config, DB and migration runner, health check.
2. Auth with user isolation.
3. Task CRUD API with tests.
4. Activity log wired into every write.
5. Pages: tasks list, edit modal, dashboard, activity, settings.
6. Tags, badges, counters, dark mode, responsive pass.
7. Reminder cron endpoint and SMTP notifier.
8. Seed script, README, deploy files.

## Deployment on Compute Engine

Claude Code writes the files in `deploy/` and the README steps; the team runs the cloud steps by hand.

1. Create an e2-micro VM, Ubuntu 22.04 LTS, region us-central1, 30 GB standard disk. Allow HTTP and HTTPS traffic (ports 80, 443). Connect via SSH.
2. Set a budget alert on the billing account before anything else.
3. Install Python, venv, Nginx and certbot; clone the repo; create `.env`; run migrations and the seed script.
4. Install `deploy/startby.service`: Gunicorn with 2 workers bound to 127.0.0.1:8000, `Restart=always`, starts on boot.
5. Install `deploy/nginx.conf`: proxy to Gunicorn, serve `/static` directly, redirect 80 to 443.
6. Point a free DuckDNS subdomain at the VM's external IP; run certbot for the certificate and auto-renewal.
7. Create ONE Cloud Scheduler job: every 5 minutes, POST to `https://<domain>/api/cron/reminders` with header `X-Cron-Secret`.
8. Add a Cloud Monitoring uptime check on `/healthz`.

`deploy/setup.sh` automates steps 3 to 5 so the VM can be rebuilt quickly.

## Acceptance criteria

Phase 1 is done when every box is ticked on the deployed VM, not just locally.

- [ ] Add, edit, complete, reopen and delete a task; refresh the page and everything persists.
- [ ] Restart the VM; the app comes back on its own and data is intact.
- [ ] User A cannot see or change User B's tasks (API returns 404).
- [ ] Overdue badge appears for a pending task with a past due date.
- [ ] Tag filter, status tabs and search all work together.
- [ ] Counters update immediately after each action.
- [ ] Activity page shows every action with old and new values.
- [ ] Dark mode persists across logout and login, with no flash on load.
- [ ] Layout works at 360 px, 768 px and 1280 px widths.
- [ ] A task due in under 24 hours triggers exactly one email, even after several cron runs.
- [ ] HTTP redirects to HTTPS; the certificate is valid.
- [ ] `/healthz` returns 200; the uptime check is green.
- [ ] `pytest` passes; README lets a new teammate run the app locally in under 10 minutes.

## Phase 2 preview (do not build)

Listed only so Phase 1 leaves room for them. A separate PRD will follow.

| Feature | Plugs into |
| --- | --- |
| Effort estimate + start-by time (due minus adjusted effort minus buffer) | New task columns via migration 002; `serialize_task` |
| Risk radar (green / amber / red) and "Do this now" card | `serialize_task`; dashboard endpoint; task card renderer |
| Start-now reminders | New rule in reminder\_service; new reminder kind |
| Estimate correction (per-tag bias multiplier, one-tap actual time on completion) | `on_task_completed` hook; new insights endpoint |
| Smart capture with Gemini (paste text or PDF, preview, confirm) | New capture blueprint and service |
| Overload warning and estimation report card | Dashboard endpoint; new insights page |

# Implementation plan

Nine short sprints from Oct 1 to Oct 5 keep `main` deployable at every step: Phase 1 is frozen and tagged `v1.0` on Oct 3, Phase 2 ships behind feature flags on Oct 4, and Oct 5 is hardening and presentation only.

## Sprint schedule

Each sprint ends with its exit gate passing. If a gate fails, the next sprint does not start; fix first.

| Sprint | When | Scope | Exit gate |
| --- | --- | --- | --- |
| S0 Setup | Oct 1 night | Repo, branch rules, GitHub Actions running pytest on every push, `.env.example`, VM created in us-central1, budget alert, DuckDNS name | Empty Flask app reachable on the VM's IP |
| S1 Foundation | Oct 2 AM | App factory, config, DB + migration runner, `001_init.sql`, auth, user isolation, `/healthz`, systemd + Nginx | Auth tests pass; app deployed and survives a VM reboot |
| S2 Core CRUD | Oct 2 PM | Task repo, service, API; soft delete; `is_overdue`; activity log wired into every write | All CRUD, isolation and activity tests pass on CI |
| S3 UI | Oct 3 AM | Base layout, tasks page, edit modal, dashboard, activity page, tags, badges, counters, empty states, toasts | Manual smoke test of the full add → edit → complete → delete → refresh flow on the VM |
| S4 Finish Phase 1 | Oct 3 PM | Dark mode, responsive pass, reminder cron + SMTP notifier, HTTPS, Cloud Scheduler job, uptime check, seed script, README | Every Phase 1 acceptance box ticked on the VM; tag `v1.0` |
| S5 Phase 2a | Oct 4 AM | Migration 002, effort estimate, multiplier, start-by, risk radar, "Do this now" card, start-now reminder rule | Phase 1 suite still green; new invariant tests pass; flag off = v1.0 behaviour |
| S6 Phase 2b | Oct 4 PM | Smart capture (Gemini + regex fallback), one-tap actual time, estimate correction, overload warning, report card, synthetic history seed | Capture works with AI on AND with AI key removed; tag `v1.1` |
| S7 Hardening | Oct 5 AM | Full regression, edge-case bug bash, Locust load test, log review; code freeze at 12:00 | Zero open P0/P1 bugs; p95 latency recorded |
| S8 Present | Oct 5 PM | Architecture diagram, 8–10 slides, video walkthrough, two demo rehearsals on the live VM | Submission emailed; demo account reset to clean seed data |

If the team falls behind, cut in this order: report card, overload warning, PDF upload (keep paste-text capture). Never cut a Phase 1 feature or a test.

## Logic invariants

These rules must hold at all times. Each one gets at least one automated test, written in the same sprint as the code it protects.

| ID | Rule | Sprint | Test |
| --- | --- | --- | --- |
| I1 | A user can only read or change their own tasks and activity. | S1–S2 | Other user's task ID returns 404 on every task endpoint |
| I2 | Soft-deleted tasks never appear in lists, counts, dashboard, reminders or insights. | S2 | Delete, then assert absent from every read endpoint and the cron query |
| I3 | total = completed + pending, and overdue ⊆ pending. | S2 | Counter test over a mixed seed set |
| I4 | Overdue means pending AND due\_at < now (UTC). Done tasks are never overdue; tasks with no due date are never overdue. | S2 | Boundary tests at due\_at = now ± 1 second |
| I5 | Every successful write creates exactly one activity row per action (one per changed field for updates); a failed write creates none. | S2 | Write + rollback tests; unchanged-field PATCH logs nothing |
| I6 | completed\_at is set if and only if status = done. | S2 | Complete then reopen, assert both fields |
| I7 | Each reminder kind is sent at most once per task, even when cron runs repeatedly or overlaps. | S4 | Run cron 3 times; assert one email; UNIQUE constraint enforced |
| I8 | Changing due\_at clears that task's due\_soon and overdue reminder records, so the new deadline can remind again. | S4 | Remind, move due date, remind again |
| I9 | All stored times are UTC; display converts to the user's timezone. | S1–S2 | IST user creating "5 PM" stores 11:30 UTC |
| I10 | start\_by = due\_at − estimate × multiplier × (1 + buffer). It is null if due\_at or estimate is missing. | S5 | Formula tests incl. nulls |
| I11 | start\_by is recomputed whenever due\_at, estimate or that tag's multiplier changes; completing a task recomputes pending tasks of the same tag. | S5–S6 | Change each input, assert new start\_by |
| I12 | Risk: done or no start\_by → none; now ≥ start\_by → red; start\_by within 24 h → amber; otherwise green. | S5 | One test per branch |
| I13 | Multiplier per user and tag = exp((n × mean log ratio + 5 × ln 1.5) ÷ (n + 5)), clamped to \[1.0, 3.0\]; n = 0 gives exactly 1.5. | S6 | Cold start, worked example (3 tasks at 2.0, 2.5, 2.0 → 1.72), clamp tests |
| I14 | Smart capture never writes to the DB until the user confirms; confirm saves only ticked rows and logs them as created. | S6 | Preview call leaves task count unchanged |
| I15 | With every Phase 2 flag off, behaviour and API responses match v1.0 exactly. | S5–S6 | Run the v1.0 test suite with flags off |

## Safety practices

These practices make breakage hard to introduce and quick to undo.

- **Branching:** one branch per sprint (`s2-crud`, `s5-phase2a`). Merge to `main` only when CI is green and the exit gate passes. Nobody pushes directly to `main`.
- **CI on every push:** GitHub Actions runs `pytest` plus a lint step (ruff). A red build blocks the merge.
- **Tests grow, never shrink:** the full suite runs every time, so a Phase 2 change that breaks a Phase 1 rule fails immediately. Deleting or skipping a test needs team agreement.
- **Feature flags:** Phase 2 features read `FEATURE_ESTIMATES`, `FEATURE_SMART_CAPTURE`, `FEATURE_INSIGHTS` from `.env`. If something breaks during the demo, turn the flag off and restart: the app falls back to v1.0 behaviour.
- **Additive migrations only:** new numbered files, new nullable columns, no renames or drops. Before every migration on the VM, copy the database file (`cp app.db backups/app-<date>.db`).
- **Tagged releases:** `v1.0` after S4, `v1.1` after S6. Rollback = `git checkout <tag>`, restart the service, restore the matching DB backup.
- **Post-deploy smoke test:** `scripts/smoke.sh` hits `/healthz`, logs in as the demo user, creates, edits, completes and deletes a task, and checks counts. Run it after every deploy.
- **External calls fail safe:** Gemini and SMTP calls have timeouts (10 s), one retry with backoff, and errors are logged, never shown as a crash. Capture falls back to regex + `dateparser`; a failed email does not record a reminder as sent, so it retries on the next run.
- **Cron is idempotent and protected:** it checks `X-Cron-Secret`, uses the UNIQUE constraint to avoid duplicates, and processes at most 100 tasks per run.

## Edge cases to test (S7 bug bash)

Work through this list on the live VM; each failure becomes a test before it is fixed.

- [ ] Title with emoji, Tamil text, 200 characters, and HTML tags (must render escaped, no XSS).
- [ ] Due date exactly now, in the past at creation, and far future (2030).
- [ ] Task created at 11:50 PM IST that is due "tomorrow" lands on the correct date in UTC.
- [ ] Double-clicking Save, Complete or Delete performs the action once.
- [ ] Editing a task in two tabs: the last save wins and both edits appear in the activity log.
- [ ] Completing, reopening and completing again keeps counts and completed\_at correct.
- [ ] Deleting a task that has reminders recorded; cron afterwards sends nothing for it.
- [ ] Expired login session mid-edit shows a clear message, not a broken page.
- [ ] Cron called with a wrong or missing secret returns 401 and sends nothing.
- [ ] SMTP down: no crash, reminder retried on the next run.
- [ ] Gemini key removed or quota hit: capture still returns drafts via fallback.
- [ ] Capture input with no dates, a PDF with no text, and a 20-page PDF.
- [ ] Estimate of 0, negative, or 500 hours is rejected with a clear message.
- [ ] A tag with 50 completed tasks still keeps its multiplier within 1.0–3.0.
- [ ] Phone at 360 px: edit modal fits and scrolls; nothing overflows sideways.

## Definition of done (every task, every sprint)

- [ ] Code follows the layering: routes → services → repositories.
- [ ] Tests written for the new logic, including at least one failure case; full suite green on CI.
- [ ] Activity log entries correct for any new write.
- [ ] Works in light and dark mode, and on mobile width.
- [ ] Deployed to the VM and smoke test passes.
- [ ] README or PRD updated if behaviour changed.
