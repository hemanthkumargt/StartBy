# 1. Flask (Python) over Node/Express

**Status:** Accepted

## Context

Six students, four days of build time, a team that is more consistently
comfortable in Python (coursework, DSA practice) than in JavaScript backends.
The app itself is simple CRUD plus a cron-triggered email job — it has no
need for Node's strengths (heavy concurrency, streaming, a unified
language with the frontend).

## Decision

Use Flask with an app factory and blueprints, not Express/Node.

## Alternatives considered

- **Node + Express**: same-language frontend/backend is appealing, but the
  team has less collective Node experience, and Phase 2's AI capture
  (Gemini) and PDF text extraction have simpler, better-documented Python
  libraries (`google-genai`, `pypdf`) than their Node equivalents at the
  time of writing.
- **Django**: batteries-included (admin, ORM, auth) would save boilerplate,
  but the PRD explicitly bans an ORM (parameterised SQL only, for
  transparency and to keep the data model easy to reason about under time
  pressure) and we don't need Django's admin or templating opinions.

## Consequences

- Smaller ecosystem for some things (no Express-style middleware chains),
  but Flask's blueprint + app-factory pattern gives us the same separation
  of concerns (`routes → services → repositories`) with far less framework
  to learn in four days.
- Gunicorn + Flask is a well-worn, low-RAM-footprint combination that fits
  the e2-micro VM's 1 GB RAM comfortably at 2 workers.
