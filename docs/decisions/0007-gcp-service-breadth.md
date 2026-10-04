# 7. Which additional GCP services to adopt for service breadth

**Status:** Superseded by [ADR 0008](0008-eleven-service-gcp-stack.md) (the team adopted a larger 11-service stack on 2026-10-03)

## Context

The judging mentor (Vinith) reviewed the use-case fit and asked the team to
also show breadth of GCP tooling: the number of distinct GCP services used
and justified, not just whether the app works. Before this, the plan used
three GCP services (Compute Engine, Cloud Scheduler, Cloud Monitoring/
Logging via the Ops Agent) plus the Gemini API already scoped for Phase 2
smart capture. The team researched a longer list of candidate services and
needed a decision on which to actually adopt under the project's existing,
non-negotiable constraints: ₹0 cost, a single e2-micro VM (1 GB RAM), and a
hard code freeze on 2026-10-05 12:00 IST.

## Decision

Adopt two additional services now, document two as considered alternatives
rather than second live integrations, and leave one open pending a team
decision because it conflicts with an existing architecture rule.

**Adopted:**
- **Secret Manager** — `SECRET_KEY`, `SMTP_PASSWORD`, `CRON_SECRET` are read
  from Secret Manager at boot instead of a `.env` file sitting on the VM's
  disk. Free tier (6 secret versions/month) comfortably covers 3-4 secrets.
- **Cloud Storage** — a nightly job (triggered by a second Cloud Scheduler
  job, within the 3-jobs-free limit) copies the SQLite file to a bucket.
  Free tier is 5 GB-months, far more than this database needs.

**Documented as considered, not deployed:**
- **Cloud Build + Artifact Registry** — could run tests and deploy on every
  push, replacing or supplementing the existing GitHub Actions workflow.
  Free tier (120 build-minutes/day) is generous. Not adopted before the
  freeze: migrating CI this close to the deadline risks a broken pipeline
  during the one week it matters most, for a judging criterion ("alternatives
  considered") this ADR already satisfies without the migration.
- **Cloud Natural Language API** — entity/date detection in pasted task
  text. Functionally redundant with the Gemini + regex/`dateparser` pipeline
  already planned for Feature 5 (smart capture): adding a third extraction
  path for the same job is more surface area to maintain, not more
  capability.

**Open, needs the team's decision:**
- **Cloud Run Functions** (to run the Gemini/PDF step as a separate
  function) directly conflicts with CLAUDE.md's "no Cloud Functions" rule,
  which exists specifically to keep the architecture at one VM with zero
  extra deployed surfaces for the e2-micro's 1 GB RAM to carry. This is a
  real architecture change — a second thing that can fail, a second thing
  to monitor and secure — not a docs update, so it isn't adopted by this
  ADR. Revisit only if the team explicitly decides the service-breadth
  criterion outweighs the simplicity the single-VM design was chosen for.

## Alternatives considered

- **Document AI** for PDF task/date extraction: the team's own research
  could not confirm a free tier. `pypdf` (already an allowed dependency for
  Feature 5's PDF fallback) covers the same extraction need without that
  cost uncertainty, so this was dropped rather than risking the ₹0 budget.
- **Adopting every service on the candidate list**: rejected outright.
  Padding the architecture with unused integrations to raise a count would
  read as exactly that in a demo walkthrough, and several candidates (Cloud
  Run Functions, Document AI) carry real cost or architecture risk this
  close to the freeze. Two genuinely useful, low-risk additions plus two
  well-reasoned "considered but not built" writeups serves both the breadth
  criterion and the original "clean architecture" one.

## Consequences

- `deploy/README-deploy.md` needs a new section for provisioning Secret
  Manager secrets and the Cloud Storage bucket + backup job during VM setup
  (not yet written as of this ADR).
- `app/config.py` needs to read secrets from the Secret Manager client
  library when running on GCP, with the existing `.env`/`python-dotenv` path
  kept for local development (not yet implemented as of this ADR).
- The backup job is a second Cloud Scheduler job, bringing total usage to
  2 of the 3 free jobs per billing account — no further free Cloud Scheduler
  jobs are available without this being revisited.
- If the team later decides to adopt Cloud Run Functions despite the
  conflict above, CLAUDE.md section 3's "no Cloud Functions" rule must be
  updated explicitly (not silently bypassed) so the constraint stays
  accurate for whoever reads it next.
