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
5. **Phase 2 is back in scope.** Team decision (2026-10-03) reverses the 2026-10-02 "drop Phase 2" decision: build all six Phase 2 features from the PRD preview, plus a new seventh feature, **Adaptive Replanning**, not in the original PRD — automatically recompute a task's `start_by` recommendation when the user misses it (now past `start_by`, task still pending) or changes the due date/estimate, rather than only recomputing on an explicit input change. This is substantially invariant I11 (recompute on due_at/estimate/multiplier change) plus a time-based trigger (recompute on every read when `now` has crossed `start_by` with no action taken) — treat it as part of the S5 estimate/start-by work, not a separate feature flag, since it's the same calculation re-run at a different trigger.
   - Build order (one feature at a time; each gets its own deep code review via the `code-review` skill and a manual browser test pass before moving to the next): (1) effort estimate + start_by formula + Adaptive Replanning's missed-start-time recompute, (2) risk radar + "Do this now" card, (3) start-now reminders, (4) per-tag estimate-correction multiplier (feeds back into 1's formula), (5) smart capture (Gemini + regex/dateparser fallback), (6) overload warning + report card.
   - Every Phase 2 feature still sits behind its feature flag (`FEATURE_ESTIMATES`, `FEATURE_SMART_CAPTURE`, `FEATURE_INSIGHTS`); with every flag off, behaviour must still equal `v1.0` exactly (I15).
   - **Known risk, flagged to the user twice already and accepted**: code freeze is 2026-10-05 12:00 IST and the app is not yet deployed to a VM (that's still step 2/6 of the original brief, untouched). Building all of Phase 2 before deploying means deployment — the one mandatory, non-negotiable deliverable — gets less runway. Proceeding per explicit instruction; the plan is now to deploy once all 7 features are built and tested, not before.
6. Never weaken, skip or delete a test to make CI pass. Fix the code, or ask.
7. Ask before adding any dependency not listed in section 5.
8. Small commits, Conventional Commits style: `feat(tasks): add soft delete`, `test(reminders): idempotency`, `fix(ui): modal overflow on 360px`.

## 3. Outside factors and constraints (read carefully)

### Cost — everything must stay at ₹0

* Compute Engine e2-micro only, region us-central1 (Always Free applies only in us-west1, us-central1, us-east1). 30 GB standard disk. Any other size/region costs money.
* e2-micro has 1 GB RAM: Gunicorn `--workers 2`, no Docker, no Redis, no extra daemons beyond Nginx and the Ops Agent.
* Cloud Scheduler: 3 free jobs per billing account in total. We use exactly ONE.
* Do not create static IPs, load balancers, or Cloud SQL.
* No paid APIs. Gemini via a free Google AI Studio key only.

### GCP service breadth (added 2026-10-03, team decision pending)

The judging mentor (Vinith) flagged that the number of distinct GCP services/tools used and justified is a scored criterion on its own, separate from the use case itself. The single-VM design keeps cost and operational risk at zero, which is still non-negotiable — but it also means the services list was thin. Decide the items below at the team's 5:30 meeting, since several interact with the ₹0 and e2-micro constraints above.

**Already in the plan (count these first — 4 services, no new decision needed):** Compute Engine, Cloud Scheduler, Cloud Monitoring + Cloud Logging (via the Ops Agent), and the Gemini API (Phase 2 smart capture, already scoped below).

**Proposed additions — low risk, recommend adopting:**
* **Secret Manager** — store `SECRET_KEY`, `SMTP_PASSWORD`, `CRON_SECRET` here instead of in the VM's `.env`. Free tier: 6 secret versions/month, far more than our ~3-4 secrets need. Small setup cost (the app reads secrets at boot via the client library instead of `python-dotenv`), and it directly answers the judging criterion for "security awareness" too, not just service count.
* **Cloud Storage** — a nightly cron step (or a second, tiny Cloud Scheduler job) copies the SQLite file to a bucket. Free tier: 5 GB-months, trivially enough for this DB's size. Removes the single VM disk as the one copy of all data, which is a real resiliency improvement worth having regardless of the judging angle.

**Proposed additions — worth documenting as "considered," not necessarily deploying before the freeze:**
* **Cloud Build + Artifact Registry** — could replace or sit alongside the existing GitHub Actions CI to run tests/deploy on push. Free tier (120 build-minutes/day) comfortably covers this repo. Real setup work this close to the Oct 5 freeze; if time is short, write the ADR for it (judges score "alternatives considered") and keep GitHub Actions as the actual CI, rather than risk a half-migrated pipeline the week of the demo.
* **Cloud Natural Language API** — entity/date detection in pasted task text. Functionally overlaps with what Gemini already does for Feature 5 (smart capture) plus the regex/`dateparser` fallback; adding a third extraction path is redundant surface area for the same job. Worth a line in the roadmap as a considered alternative, not a second live integration.

**Flagged conflict — needs a team decision, not a unilateral change:**
* **Cloud Run Functions** (to run the Gemini/PDF step as a separate function) directly contradicts the "no Cloud Functions" rule a few lines above, which exists specifically to keep the architecture at one VM with zero extra moving parts the e2-micro's 1 GB RAM has to carry. Don't add this without the team explicitly deciding to relax that constraint — it's a real architecture change (a second deployed surface, a second place that can fail, a second thing to monitor), not a documentation update.
* **Document AI** — PDF task/date extraction. The team's own research couldn't confirm a free tier; don't add a service to the architecture with an unconfirmed ₹0 story. `pypdf` (already an allowed dependency, below) covers the same PDF-text-extraction need for Feature 5 without this risk.

### Gemini free tier

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

Runtime: `flask`, `flask-login`, `flask-wtf` (CSRF), `python-dotenv`, `gunicorn`, `dateparser`, `google-genai` (S6 smart capture), `pypdf` (S6, PDF text extraction fallback input). Dev: `pytest`, `pytest-cov`, `freezegun`, `ruff`, `locust`. Frontend: no frameworks, no CDN scripts. Vanilla JS modules + CSS only.

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
* Every PRD logic invariant (I1–I15) has a named test, e.g. `test_I7_reminder_sent_once`. Adaptive Replanning (section 2.5) needs its own test(s) alongside I11/I12 since it adds a time-based recompute trigger those don't cover.
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
* From S6: `--history` flag adds ~200 synthetic completed tasks with realistic actual/estimate ratios per tag (e.g. study ~1.6×, work ~1.3×, personal ~1.1×), clearly marked `source='seed'`, for the estimate-multiplier feature to have something to learn from in the demo.

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
