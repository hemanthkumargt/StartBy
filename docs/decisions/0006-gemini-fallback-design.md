# 6. Gemini with a regex/dateparser fallback (Phase 2 design)

**Status:** Accepted (design only — not yet built; lands in Sprint S6 behind
`FEATURE_SMART_CAPTURE`)

## Context

Phase 2's "smart capture" lets a student paste free text or a PDF (a
syllabus, an email, a WhatsApp forward) and get draft tasks back. This is
the one place the app calls an external AI service, which brings three
risks the rest of the app doesn't have: the free Gemini tier is rate-limited
and can be slow or unavailable, its output is unstructured text that must
not be trusted blindly, and free-tier prompts may be used by Google for
model improvement.

## Decision

- Call Gemini (model name read from `GEMINI_MODEL` in `.env`, never
  hard-coded, since free-tier model availability changes) with a structured
  JSON schema for the response, and **re-validate every field server-side
  anyway** — the schema constrains the shape of what comes back, not its
  correctness.
- Wrap the call with a 10-second timeout and exactly one retry with
  backoff, matching the same external-call safety pattern already used for
  SMTP (`app/services/notifier.py`).
- On any failure — timeout, HTTP 429, missing/invalid API key, or malformed
  output — fall back to a regex + `dateparser` extractor that produces a
  cruder but still usable draft (titles split on lines/bullets, dates
  parsed heuristically). The user always gets *something* back; capture
  never hard-fails because Gemini is unavailable.
- Never write anything to the database until the user reviews and confirms
  the draft (invariant I14) — Gemini's output, like any external input, is
  untrusted until a person approves it.
- Demo and develop only with sample/synthetic text, never real personal
  data, since free-tier prompts may be used for model training.

## Alternatives considered

- **No AI fallback (fail loudly if Gemini is down)**: simpler, but directly
  contradicts the PRD's safety rule that external calls must fail safe, and
  would make the demo fragile to exactly the kind of rate-limiting the free
  tier is prone to.
- **A fine-tuned local model**: avoids the external dependency entirely, but
  is out of scope for a free-tier, four-day hackathon build, and the
  e2-micro VM's 1 GB RAM has no headroom to run a local model anyway.

## Consequences

- Two code paths produce a task draft (Gemini, and the regex fallback), and
  both must be exercised by tests, including the "Gemini key removed or
  quota hit" edge case from the PRD's S7 bug-bash list.
- The feature flag (`FEATURE_SMART_CAPTURE`) means this entire path can be
  switched off instantly during the live demo if something goes wrong,
  falling back to exact v1.0 behaviour (invariant I15).
