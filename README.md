# StartBy

A task manager web app built for the NPN GCP Hackathon (Use Case 1), deployed
on a single Google Compute Engine VM at ₹0 cost. See [`PRD.md`](PRD.md) for
the full spec and [`CLAUDE.md`](CLAUDE.md) for how this repo is built sprint
by sprint.

**Status: Sprint S1 (Foundation) in progress.** Auth, the database +
migrations, and `/healthz` are working. Task CRUD and the real UI land in
S2–S3.

## Local setup (~5 minutes)

```bash
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
cp .env.example .env             # edit SECRET_KEY at minimum
python wsgi.py                   # http://127.0.0.1:5000
```

Visit `/register` to create an account, then you're on the homepage.
The SQLite database is created automatically at `instance/app.db` (gitignored)
and migrated on first run — nothing else to set up.

## Tests

```bash
pytest                                  # run the suite
pytest --cov=app --cov-report=term-missing   # with coverage
ruff check .                            # lint
```

## Architecture (current)

```
browser → Flask (routes → services → repositories) → SQLite
```

Routes handle HTTP only, services hold business rules, repositories hold
parameterised SQL — no ORM. Full architecture diagram (including Nginx,
Gunicorn, Cloud Scheduler and Gemini) lands in S4/S8 once those pieces exist.

## Deploy

Not yet deployed. `deploy/` and `deploy/README-deploy.md` land in Sprint S4.
