# 2. SQLite over Cloud SQL

**Status:** Accepted

## Context

The hard constraint is ₹0 cost. Cloud SQL (even its smallest tier) is not
part of GCP's Always Free program and bills continuously whether or not the
hackathon is actively being judged. Expected load is a handful of student
users during development and a live demo audience of judges — not a
production multi-tenant SaaS.

## Decision

Use SQLite via Python's built-in `sqlite3`, file-backed on the VM's disk,
with WAL mode enabled and a plain SQL migration runner (`migrations/*.sql` +
a `schema_migrations` table) instead of an ORM or a managed database.

## Alternatives considered

- **Cloud SQL (Postgres/MySQL)**: real concurrent-write scaling and managed
  backups, but costs money from the moment the instance exists, and adds a
  network hop + connection-pool complexity the project doesn't need at this
  scale.
- **A hosted free-tier Postgres (e.g. a third-party free plan)**: moves cost
  risk to a third party's definition of "free," which can change without
  notice; also adds a second platform's quirks and downtime risk the team
  would be debugging mid-hackathon.

## Consequences

- SQLite's single-writer model would struggle under genuine concurrent
  write load. Gunicorn runs 2 worker processes against the same file, and
  WAL mode is specifically there to let concurrent readers and a single
  writer coexist without `database is locked` errors under this app's
  actual traffic pattern.
- Backups are a file copy (`cp app.db backups/app-<date>.db`), which is
  simpler to reason about under deadline pressure than managed snapshots,
  but is a manual step the team must remember before each migration
  (documented in `deploy/README-deploy.md`).
- If StartBy ever needed real multi-tenant scale, this is the first piece
  that would be swapped — the repository layer (`app/repositories/`) is the
  seam where that change would happen without touching services or routes.
