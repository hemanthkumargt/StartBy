# StartBy / Kairo — deep code review with human factors (2026-10-04)

**Scope:** everything on branch `feat/new-ui-phase2` (teammate's UI merged + Phase 2 features + GCP layer + Calendar), uncommitted.
**Method:** four independent read-only reviewers (data-entry errors · time/logic · UX & accessibility · operations/misuse), each proving claims with the Flask test client, freezegun or small scripts, plus my own hands-on pass in a browser (desktop and 375px phone). I re-ran the highest-impact claims myself before including them.
**Baseline:** 324 automated tests pass, ruff clean. None of the problems below is caught by that suite — it has no browser or JS tests, which is why most of the worst items are UI/behaviour issues.

Origin tags: **[T]** teammate's UI branch, **[P2]** our Phase 2 code, **[OPS]** deploy/config.

---

## Fix before the demo (high impact, mostly small)

| # | Finding | Why a human hits it | Where | Fix |
|---|---|---|---|---|
| 1 | **Light mode never sticks [T].** `data-theme` is `'dark' if … else 'dark'` — both branches dark. | User picks Light, refreshes, gets Dark again; Settings checkbox shows unchecked. Verified. | `templates/base.html:2` | change the `else` to `'light'` (one word) |
| 2 | **Phone layout is broken [T].** The hamburger bar sits *beside* the content in a flex row, squeezing the page into ~200px; text and buttons run off the right edge. Measured at 375px. | Anyone opening it on a phone (judges often do) sees a cramped, clipped page. | `app.css` `.app-shell` / `.mobile-top-bar` | `flex-direction: column` for `.app-shell` at ≤768px |
| 3 | **Times shown ≠ times typed.** New accounts get `Asia/Kolkata` regardless of the browser; the edit form uses the *browser* timezone but cards/emails use the *Settings* timezone; only 8 zones offered. | A user whose laptop zone differs types 5 PM, the card says 2:30 AM next day; "fixing" it shifts the deadline by hours. Capture drafts have the mirror problem. Verified with `TZ=America/New_York`. | `static/js/datetime.js:37-57`, `routes/auth.py:33`, `settings.html:551` | default tz from `Intl…resolvedOptions().timeZone` at signup; format/parse form values in the Settings tz (or label the field with its zone) |
| 4 | **Smart-capture fallback silently gets dates wrong.** "Submit Project 2 by Friday 5pm" → a Friday *in the past*; "Quiz 2 on 10/12" → year **2112**; "Read chapter 5 by Friday" → Monday; "Lab due Monday 9am" → Friday; ISO dates ignored; year-less past date → next year; Hindi/Hinglish ("kal tak") → no date, no warning. Reproduced. | This is what runs whenever Gemini is down/over quota — i.e. likely during the demo. Rows look plausible, so people save them. | `services/fallback_extractor.py:85-113` | flag rows with no/past/implausible date (>2y) in the UI; treat a bare number next to a date as a title token; handle ISO + weekday+time explicitly; show "no date found" per row |
| 5 | **Login/register limits lock out real people.** 10 logins/min and 5 registers/min *per IP*, successes included; `BEHIND_PROXY` is only in the GCP env template, so a manual deploy rate-limits the **whole site as one client** (11th login by anyone → 429). 20 judges behind one NAT, or one prankster, can lock everyone out. Verified. | The demo room shares one public IP. | `routes/auth.py`, `ratelimit.py`, `.env.example`, README step 5 | limit failures only, key on (IP, email), raise to ~60/min per IP and ~30 registers; add `BEHIND_PROXY=1` to `.env.example` + README; pre-create judge accounts |
| 6 | **Dashboard shows invented data and dead links [T].** "Productivity & Velocity", "Steady Progress", "0%", "0 of 0 done" per category are static HTML nothing updates; "Pending Queue"/"Study Hub" shortcuts go to `/tasks?status=…` but the page ignores the query string. | A user with 10 done tasks still sees 0% and a green badge; shortcuts silently show the unfiltered list. | `home.html:163-267`, `tasks.js` | wire to `/api/dashboard` or delete the card; read `location.search` into the filters |
| 7 | **One bad row can stop reminders for everyone [P2].** A title with a newline makes the email builder throw; the send "fails", is released, and 100 such rows fill the `LIMIT 100` forever so later users get nothing. Titles with newlines/NUL are accepted (verified: 201). A dead SMTP also costs ~22s per candidate inside one HTTP request. | Pasted PDF/WhatsApp text commonly contains newlines. | `reminder_repo.py:6-42`, `reminder_service.py:36-46`, `task_service._validate_title` | collapse control chars in titles; sanitize subject; per-run failure circuit-breaker; skip rows that failed this run |
| 8 | **Seeding/deploying on the real VM trips over itself [OPS].** `seed.py` doesn't load Secret Manager, so on a GCP VM it refuses to start (verified message); it also creates `demo@startby.local` / `change-me` on a public site; `setup.sh` re-run after first install likely fails (`chmod`/`pip` on www-data-owned files) and never restarts the service though the README says it does; the documented `cp app.db` backup/restore is unsafe with WAL, and the GCS restore was never written down or tried. | A fix at 11:00 on freeze day. | `scripts/seed.py`, `deploy/setup.sh`, `deploy/README-deploy.md` | call the secrets loader in seed.py; refuse placeholder seed password in production; run update steps as www-data + `systemctl restart`; document `sqlite3 .backup` + a tested GCS restore |

## Medium — wrong behaviour a user will notice

**Logic / numbers [P2]**
- **One typo skews your pace forever.** Estimate 0.25h, actual typed as 100 → multiplier jumps to 3.00 (6h54m lead for a 2h task); no way to correct `actual_hours` afterwards. → clamp each log-ratio to ~[ln 0.33, ln 3] and allow correcting actual hours. (`estimate_service.py:44-51,145-161`)
- **"Do this now" can pick a task abandoned six weeks ago** over one due in 30 minutes; **"Due next"** fills with 5 stale overdue tasks and never shows upcoming ones. → prefer not-yet-overdue; treat long-overdue as a separate "catch up" group. (`estimate_service.py:164`, `task_repo.py:221`)
- **Editing the estimate or tag re-sends emails already delivered** (due-soon/start-now/overdue all cleared). Only a `due_at` change should clear them. (`task_service.py:314`)
- **Late tasks get an email burst:** due in 10 min with a 6h estimate → due-soon + start-now together, overdue ten minutes later; tasks created overdue get overdue + start-now. Start-now says "to finish by your due date" then "finishes 10h after the due time". → one combined message; skip start-now once past due.
- **Emails give no time and ignore time of day:** "due within 24 hours" without saying when; a 3am start-by sends a 3am email. Server already has `utc_iso_to_local`. (`reminder_service.py`)
- Explanation text says "your completed tasks have taken about 1.57x" when it's a blend with one sample (really 2.0x). Report-card verdict ("you underestimate") shows from a single task; trend calls 0.5x→2x "steady". "0 mores" in the overload message; pile of stale tasks reads "Overloaded" forever; "late by" counts the 15% buffer; seconds-late shows "0m".
- Editing the estimate of a **completed** task returns 200 "Task saved" but is silently ignored. (`task_service.py:34-40`)
- `INSIGHTS=1` with `ESTIMATES=0` shows "workload manageable" even when data exists.

**Input handling**
- **500 instead of a clear error** for a non-string `due_at` (`{"due_at": 12345}` — verified), and for registering the same email twice at once (5 of 6 concurrent requests returned 500). → `isinstance` check; catch `IntegrityError`.
- Capture silently drops things: >25 drafts, >300 lines, repeated undated titles ("Lab / Lab"), text past the 20,000-char textarea limit, estimates under 15 min. → show "N more not shown".
- Fractions and zones misread: "slides for 2/3 people" → a date in 2027; "17:00 EST" treated as local; "24:00" → noon.
- Registration: all-space 8-char password accepted; no name length cap; `é` typed with a combining accent vs precomposed creates two accounts (login then fails from another device). → NFC-normalize, cap lengths.
- Error text uses field names ("estimate_hours must be between…"); a 10-minute task can't be logged (<0.25h); notes have no length cap (3 MB accepted); search is case-insensitive for ASCII only.

**Interface & accessibility [T unless noted]**
- **Expired session = dead end.** API 401 → a 4-second "Login required" toast and you stay on the page; a stale CSRF gives "Request failed (400)"; offline shows raw "Failed to fetch". Nothing redirects to login. (`api.js:29`) — confirmed by hand.
- **Loading forever:** Insights and Activity cards say "Loading…" permanently if the call fails; Tasks shows a blank page; dashboard counters show a fake 0.
- **Keyboard users:** the demo Autofill pill is a `div role=button` with no key handler; focus drops to `<body>` after ticking/deleting a task; the dark-mode switch has no visible focus; mobile drawer has no `aria-expanded`/Escape and stays focusable while hidden; Edit/Delete buttons are announced without the task name; no skip link.
- **Unlabeled controls (found by hand):** login submit button has no accessible name; "Remember me" is named "on"; input names equal placeholders.
- **Contrast fails (computed):** light-mode amber/green start-by text 3.2–3.8:1, badges 3.0–3.5:1, done-task titles 2.6:1, white-on-emerald button 2.5:1; dark-theme card borders 1.5:1. The darker `-text` tokens already exist in `theme.css`.
- **Tap targets** 20–36px (Edit/Delete 25px high, chips 26px, checkbox 20px) vs the 40px bar.
- **Toasts** vanish in 4s, can't be paused, errors aren't announced assertively; the "Forgot password" toast shows a developer command (`python scripts/seed.py --reset`) to end users.
- **Destructive actions without confirmation:** capture "Discard" (loses edited drafts), calendar "Disconnect"; the actual-hours dialog has no Cancel — Esc/Skip still completes the task.
- Long unbroken text in notes overflows the card (140-char URL → 793px in a 166px box); no `prefers-reduced-motion`.

**Operations [OPS]**
- SQLite write contention returns a 500 after 5s ("database is locked", reproduced) when the backup, calendar thread or second worker holds the lock. → `timeout=15` + `busy_timeout`, return 503 with a retry message.
- `CRON_SECRET` is visible to anyone with Scheduler/Tasks viewer role and in shell history from `provision.sh`; boot failure from a bad secret loops every 3s with only a log line; `CLOUD_TASKS_LOCATION` default (`asia-south1`) differs from the template (`us-central1`); `APP_BASE_URL=http://…` makes Cloud Tasks hit a 301; the alert policy emails nobody.

## Low / polish
- **Copy & brand:** pages say "Kairo", the Settings card and demo account say StartBy; adding a task has three names ("Quick Capture", "Add to Workspace", "New Task") and Smart Capture is a different thing; "My Tasks" vs "Workspace Tasks", "Activity Log" vs "Audit Trail"; "Pending" and "Start now" can both show on one task; jargon ("Priority Radar", "planning multiplier").
- **Misleading claims shown to users:** Settings says "PBKDF2-SHA256 Encrypted" but the hash is scrypt (and hashing isn't encryption); "WAL isolation", "tenant database security status", "Enter your secret credentials" are filler.
- **Dead/fake controls:** "Forgot password?" is `href="#"` (there is no password reset — a forgotten password is permanent); "Remember me" is checked by default and read nowhere.
- Third-party Google Fonts on every page (CLAUDE.md "no CDN" grey area); JetBrains Mono referenced but never loaded; stray `}` in `theme.css:176`; duplicate `.toast` blocks; two tabs editing one task is last-write-wins.
- Two Calendar caveats: events don't move when `start_by` drifts (no hook fires), and Calendar needs a public HTTPS domain.

## Checked and fine (so you don't re-test)
Formulas for start-by, risk boundaries and the learned multiplier; DST handling (New York gap/overlap, London overlap); reminder claims are atomic and a failed send releases the claim; stale Cloud Tasks callbacks are harmless; search escapes `%`/`_`; 200-char limit counts characters correctly; XSS in titles/notes/explanations (rendered as text); double-submit disabled on every form; 401 on `/api/*` is JSON; `.env` untracked; secrets never logged; production refuses placeholder secrets; per-user isolation (other users' tasks → 404) across all endpoints; Gemini key sent in a header, not the URL; flag combinations never 500.

## Notes on this review
- One reviewer ran `seed.py` against the repo's dev database by accident (the script always targets whatever `.env` is in the repo root — itself a footgun). The demo user now has 31 tasks instead of 30. No source files were touched; `python scripts/seed.py --reset` restores it.
- Not verified: real-device 360px rendering (the pane's emulation was unreliable for the UX reviewer; my own 375px measurements agree with finding #2), a real Gemini/Google call, and `provision.sh` against a real project.
