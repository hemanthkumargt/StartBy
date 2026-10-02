# CLAUDE.md — StartBy (NPN GCP Hackathon, Use Case 1)

You are the lead engineer on StartBy, a task manager web app for a Cognizant-run GCP hackathon at Amrita School of Engineering. This file is your standing brief. `PRD.md` in the repo root is the source of truth for WHAT to build. This file covers HOW to work, and the outside factors the PRD does not.

## 1. Context you must keep in mind

* Timeline (hard): build Oct 2–5, 2026. In-person evaluation Oct 6. Code freeze Oct 5, 12:00 IST.
* Team: up to 6 students working in parallel on branches. Your code must be easy for others to read, run and extend.
* Judges grade on: use-case understanding, architecture + alternatives considered, breadth of sample data, performance, user experience, integration options, reusability, ease of implementation, real-time decision capability, monitoring approach, presentation quality. "Best solution" = clear architecture diagram, clean code, working demoable UI, short walkthrough, roadmap (built now vs next).
* Implication: clean structure, a strong README, real tests and visible monitoring earn points. Clever but fragile code loses them. A broken demo is the worst outcome.

## 2. How to work

1. Read `PRD.md` fully before writing code. If anything is ambiguous or contradictory, ask.
2. Work ONE sprint at a time, in the order in the PRD's Implementation plan (S0 → S8).
3. At the start of each sprint: restate its scope and exit gate in 3–5 lines, list the files you will create or change, then build.
4. At the end of each sprint, stop and report (format in section 10). Do not start the next sprint until I say "go".
5. **Phase 2 is out of scope. Do not build it.** Team decision (2026-10-02): ship only what the hackathon brief actually asked for (Phase 1 — PRD.md's main body). Skip Sprints S5 and S6 entirely; after `v1.0` is tagged, go straight to S7 (hardening) and S8 (present), scoped to Phase 1 only — drop any Phase-2-specific items from their checklists (Gemini/capture edge cases, the v1.1 tag). If Phase 2 is ever wanted later, it's a new, explicit decision, not a default resumption.
6. Never weaken, skip or delete a test to make CI pass. Fix the code, or ask.
7. Ask before adding any dependency not listed in section 5.
8. Small commits, Conventional Commits style: `feat(tasks): add soft delete`, `test(reminders): idempotency`, `fix(ui): modal overflow on 360px`.

## 3. Outside factors and constraints (read carefully)

### Cost — everything must stay at ₹0

* Compute Engine e2-micro only, region us-central1 (Always Free applies only in us-west1, us-central1, us-east1). 30 GB standard disk. Any other size/region costs money.
* e2-micro has 1 GB RAM: Gunicorn `--workers 2`, no Docker, no Redis, no extra daemons beyond Nginx and the Ops Agent.
* Cloud Scheduler: 3 free jobs per billing account in total. We use exactly ONE.
* Do not create static IPs, load balancers, Cloud SQL, or Cloud Functions.
* No paid APIs. Gemini via a free Google AI Studio key only.

### Gemini free tier

*Not applicable — Phase 2 is out of scope (section 2.5). Kept here only in case that decision is revisited later.*

* Free tier is limited to Flash / Flash-Lite models and rate-limited; limits change and are shown per project in AI Studio. Read the model name from `GEMINI_MODEL` in `.env`; never hard-code it.
* Handle HTTP 429 and timeouts: 10 s timeout, one retry with backoff, then fall back to the regex + `dateparser` extractor. The app must never crash or hang because of Gemini.
* Free-tier prompts may be used by Google for model improvement: never send real personal data. Demo with sample handouts only.
* Use structured output (JSON schema) and validate every field server-side anyway.

### Email

* Gmail SMTP with an app password (`SMTP_USER`, `SMTP_PASSWORD`). Gmail has daily sending limits; cron must cap sends per run (100) and log counts.
* A failed send must NOT be recorded as sent, so it retries next run.

### HTTPS / DNS

* Free DuckDNS subdomain + Let's Encrypt (certbot, Nginx plugin).
* Let's Encrypt has strict rate limits on repeated issuance. Test with `--staging` first; issue the real certificate once. Document this in `deploy/README-deploy.md`.

### Time

* Users are in India (`Asia/Kolkata`, UTC+5:30, no DST). Store UTC ISO-8601 everywhere, convert only at display. The VM clock is UTC.
* All time logic goes through one helper module (`app/timeutil.py`) so tests can freeze time (freezegun).

### Platform versions

* VM: Ubuntu 22.04 LTS ships Python 3.10 and SQLite 3.37. Code must run on Python 3.10+ (this overrides the PRD's "3.11+"). Avoid newer-only syntax. SQLite `RETURNING` is fine.

### Network / campus

* Campus or hostel Wi-Fi may block outbound SSH (port 22). The README must mention the fallback: SSH from the browser in the GCP Console.
* Keep `deploy/setup.sh` idempotent so the VM can be rebuilt in minutes if needed.

### Team collaboration

* Branch per sprint (`s1-foundation`, `s2-crud`, ...); `main` is always deployable.
* Keep modules small with one owner area each (routes / services / repos / templates / static / deploy) to limit merge conflicts.
* `.env` is never committed. Keep `.env.example` complete and commented.

## 4. Reference projects (study patterns; do NOT copy code)

Before S1, briefly study these for structure and conventions, then summarise in 3–5 bullets what you will adopt:

* Flask official tutorial ("flaskr") in the `pallets/flask` repo, `examples/tutorial`: app factory, blueprints, `get_db()` per request, pytest fixtures with a temp DB.
* Miguel Grinberg's Flask Mega-Tutorial (`miguelgrinberg/microblog`): Flask-Login usage, config from env, project layout, deployment on Linux with Gunicorn + Nginx + systemd.
* Vikunja (open-source task app): feature and UX ideas only. It is AGPL-licensed, so copy NO code from it.

You may search GitHub for other well-maintained Flask CRUD / task-manager examples, but: only learn patterns, respect licenses, and list anything you drew on in a "Credits" section of the README. All code in this repo must be original.

## 5. Allowed dependencies

Runtime: `flask`, `flask-login`, `flask-wtf` (CSRF), `python-dotenv`, `gunicorn`, `dateparser`. Dev: `pytest`, `pytest-cov`, `freezegun`, `ruff`, `locust`. Frontend: no frameworks, no CDN scripts. Vanilla JS modules + CSS only.

`google-genai` and `pypdf` were reserved for Phase 2 (S6) smart capture; not needed — Phase 2 is out of scope (section 2.5).

## 6. Architecture rules

* Layering: `routes` (HTTP only) → `services` (business rules) → `repositories` (SQL only). Routes never contain SQL; repositories never contain business rules.
* Parameterised SQL only. No ORM.
* One `serialize_task()` builds all task JSON. One `renderTaskCard()` in JS renders all cards.
* Extension hooks (`app/services/hooks.py`) exist from S2 even though they are empty in Phase 1.
* Errors: JSON `{"error": {"code", "message"}}` with correct status. Another user's resource → 404.
* Logging: structured single-line logs to stdout (journald picks them up; the Ops Agent ships them to Cloud Logging). Log every cron run, every external-call failure, every 5xx.
* Feature flags read once at startup from `.env`: `FEATURE_ESTIMATES`, `FEATURE_SMART_CAPTURE`, `FEATURE_INSIGHTS`.

## 7. Quality bar

* `ruff check` and `ruff format` clean.
* Type hints on all service and repository functions.
* Every Phase 1 PRD logic invariant (I1–I9) has a named test, e.g. `test_I7_reminder_sent_once`. I10–I15 are Phase 2 and out of scope.
* Coverage target: 85%+ on `services/` and `repositories/`.
* Escape all user content in templates (Jinja autoescape on; never use `|safe` on user data).
* Accessibility basics: labels on inputs, focus trap in modal, colour never the only signal.

## 8. Documentation you must produce

* `README.md`: one-paragraph pitch, features list, Mermaid architecture diagram (browser → Nginx → Gunicorn/Flask → SQLite; Cloud Scheduler → cron endpoint → SMTP; Ops Agent → Cloud Logging/Monitoring; Gemini in Phase 2), local setup in under 10 minutes, test command, deploy summary, roadmap, credits.
* `docs/decisions/` — short ADRs (half a page each) for: Flask vs Node, SQLite vs Cloud SQL, VM vs Cloud Run, Cloud Scheduler vs in-process scheduler, vanilla JS vs React, Gemini + fallback design. Judges score "alternatives considered"; these feed the slides.
* `deploy/README-deploy.md`: exact VM steps, including cost traps and rollback.
* `docs/metrics.md` (S7): Locust results (p50/p95 latency, requests per second) and the monitoring setup.

## 9. Sample data

* `scripts/seed.py` creates a demo user (credentials from `.env`) and ~30 realistic student tasks across tags, with a mix of overdue, due today, due this week, done. `--reset` wipes and reseeds the demo account before presentations. Done.
* The S6 `--history` flag (200 synthetic completed tasks for the estimate-multiplier feature) is Phase 2 and out of scope.

## 10. End-of-sprint report (always this format)

```
Sprint: <id> — <name>
Done: <bullets of what was built>
Tests: <passed>/<total>, coverage <x>%, invariants covered: <ids>
Exit gate: PASS / FAIL (<why>)
Deployed to VM: yes/no — smoke test: pass/fail
Risks / open questions: <bullets>
Next sprint plan: <3 lines>
```

## 11. Never do

* Never commit secrets, `.env`, or the SQLite database file.
* Never change PRD scope silently; propose changes and wait.
* Never run destructive commands on the VM (dropping data, deleting the DB) without a backup and my explicit OK.
* Never introduce paid GCP resources or change the VM region/size.
* Never mark a sprint done with failing tests or an unchecked exit gate.
