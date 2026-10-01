# 5. Vanilla JS over React

**Status:** Accepted

## Context

The UI is server-rendered Jinja2 page shells with JSON API calls for data
and actions (no full-page reloads). It needs interactivity (filters, a
modal, optimistic toggles) but not client-side routing, complex shared
state, or a component tree deep enough to need a framework's data-binding.

## Decision

Vanilla JS (native ES modules, no bundler, no build step), with one shared
card-rendering function (`renderTaskCard()` in `tasks.js`) as the single
place new fields or badges get added.

## Alternatives considered

- **React (with a build step)**: better suited to the richer interactivity
  planned for Phase 2 (live-updating risk colours, a capture-preview flow),
  but a build step is one more thing to keep working correctly on a shared
  VM under deadline pressure, and static assets served directly by Nginx
  are simpler to deploy and debug than a built JS bundle. React's component
  model would also be overkill for Phase 1's actual interaction surface
  (a handful of forms, one modal, a few list filters).
- **A lightweight reactive library (Alpine.js, htmx)**: a reasonable middle
  ground, but introduces a new dependency and mental model for a team of six
  to learn simultaneously, for a benefit (less imperative DOM code) that
  matters less than keeping everyone able to read and modify any file.

## Consequences

- Some code that a framework would generate (list re-rendering, debounced
  search) is written by hand — kept small and centralised (`api.js`,
  `tasks.js`, `toast.js`) specifically so it doesn't sprawl across pages.
- If Phase 2's UI needs (live risk colours, a multi-step capture-and-confirm
  flow) outgrow what vanilla JS comfortably expresses, this is the decision
  to revisit — nothing here blocks introducing a framework later, since all
  JS already treats the DOM as the single source of truth and talks to the
  backend only through the same JSON API a framework would also use.
