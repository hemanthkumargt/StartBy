# 3. Compute Engine VM over Cloud Run

**Status:** Accepted

## Context

The hackathon brief calls for deployment on a Google Compute Engine Linux
VM specifically. Independently of that, the app uses a file-backed SQLite
database, which needs a persistent, single, always-running filesystem.

## Decision

Deploy on a single `e2-micro` Compute Engine VM (Always Free in
`us-central1`/`us-west1`/`us-east1`), running Gunicorn behind Nginx under
systemd, rather than a serverless platform.

## Alternatives considered

- **Cloud Run**: scales to zero and is often cheaper for bursty traffic, but
  it is stateless and ephemeral by design — each instance can be destroyed
  and recreated at any time, which is incompatible with a SQLite file that
  needs to persist across requests and restarts without a shared network
  filesystem. Moving to Cloud Run would force an earlier, forced move to
  Cloud SQL, which reopens ADR 0002's cost problem.
- **App Engine**: similar persistence mismatch, plus less direct control
  over the exact process model (Gunicorn worker count tuned for 1 GB RAM)
  that the e2-micro constraint requires.

## Consequences

- We own the whole machine: OS patching, Nginx config, systemd unit, and
  the one-time HTTPS certificate setup are all our responsibility, where a
  serverless platform would have handled TLS and process supervision for
  us. `deploy/setup.sh` and `deploy/README-deploy.md` exist specifically to
  make that manual setup repeatable and fast to redo if the VM needs
  rebuilding.
- A single VM is a single point of failure with no auto-scaling — acceptable
  for a hackathon demo's traffic, not for production use at real scale.
