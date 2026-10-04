# StartBy / Kairo — deep review, round 2 (after the round-1 fixes) — 2026-10-04

**What this is:** the first report ([review-2026-10-04-human-factors.md](review-2026-10-04-human-factors.md)) listed 8 must-fix items. Those were fixed, then **four fresh reviewers** re-audited everything with the same human-factors lenses (data entry · time/logic · UX & accessibility · operations/security), checking that the fixes work and hunting for regressions. They found **~60 further issues**; the ones that could hurt a user or the demo are fixed (below), the rest are listed as open.

**Final state:** 460 automated tests pass (Python 3.14; the ops reviewer also ran the suite on Python 3.10, the VM's version), 7 Node tests for the browser date logic pass under three process timezones, ruff lint and format clean, deploy scripts pass `bash -n`. Everything is still **uncommitted and unpushed**.

## Round-1 fixes — verdicts from the re-review

| Round-1 fix | Verdict |
|---|---|
| Light mode persists | Works (server-rendered, no flash). Led to finding: nobody had ever looked at light mode — fixed contrast/logo/etc. below |
| Phone layout | Works at 360/375/414px, **but** a long unbroken URL in a note still blew the page sideways → fixed |
| One timezone for typing and display | Works in a real browser and under Node for ~150k round-trips per zone incl. Kathmandu, Lord Howe, DST. New edge cases found → fixed |
| Capture date engine | Fixed every round-1 example, but the **new engine had its own wrong-date bugs** → fixed (below) |
| Login rate limits | Worked, but a **memory-exhaustion hole** (huge email as a dict key) and limits too tight for a shared demo network → fixed |
| Dashboard fake widgets / dead shortcuts | Correct with 0, 1 and 500 tasks; deep links safe against `<script>` payloads |
| Reminder fairness | Logic fine; the failure breaker could not finish inside gunicorn's 30s timeout → fixed |
| `setup.sh` rewrite, seed script, backup docs | Mostly sound; 8 gaps (sqlite3 missing, restore/rollback recipes, no health check, …) → fixed |

## Round-2 findings that are now FIXED

**Wrong dates saved silently (the worst class — the new date engine)**
- A weekday word overrode an explicit date ("Quiz on Monday 12 Oct" saved 5 Oct) and "EOD" overrode the day → explicit dates now win; EOD is a time of day.
- Any ordinal became a date ("Revise 10th class maths" → 10 Oct) → only after a deadline word ("by the 12th").
- WhatsApp/email line timestamps became the deadline → stripped as send-time.
- "5.30pm", "5:30 p.m.", "17h30", "5pm-6pm", "5-6pm", ISO with time/offset → parsed; bare `3:45`/`John 3:16` → ignored.
- "Project 3 Nov 20", "Assignment 2 Oct 14" (a number beside a month) → ambiguous → left blank, not guessed. "Room 3/12", "page 4.5" → no longer dates.
- Hindi substring matching mangled titles (`कलम` "pen" lost its first letters; "Today's…") → word-boundary lookarounds; "Kal ki class" (yesterday's) skipped.
- Review screen now also warns when a deadline is >3 months away or invalid.
- Adversarial 20,000-character input took 5 s (quadratic) → lines capped and connector stripping is linear (<1 s in tests).

**Data corruption / outages**
- A due date near year 0001 (or "26" typed in the year field) made **every list and the reminder job return 500 for all users** → server accepts only 2000–2100, and the arithmetic can no longer overflow. The browser now reports a bad year instead of silently saving "no deadline" or erasing the existing one.
- ZWJ/ZWNJ were stripped from titles, breaking emoji families and Malayalam/Hindi/Persian words (Amrita's local language) → only zero-width *spaces* and control characters are removed.
- Editing a task's title no longer re-sends an unchanged deadline (which rewrote the instant, logged a fake "due date changed" and cleared reminders).
- An unknown-to-this-browser timezone name no longer crashes every card and form.

**Reminders**
- No more duplicate emails when you tweak an estimate or tag (only the start-now notice re-arms; a deadline change re-arms all).
- No start-now email for an already-overdue task (the overdue email covers it); overdue emails go most-recent first.
- Emails now say *when*: "due Sun 04 Oct, 17:30" in the user's own timezone.
- A run stops after 20 s and after 5 consecutive failures across *all* kinds (it was 5 per kind ≈ 5.5 min); gunicorn timeout raised to 120 s, so a slow mail server can no longer get a worker killed mid-send.

**Wrong or misleading numbers**
- "Do this now" no longer picks a task abandoned weeks ago over one due in 40 minutes; "Due next" shows upcoming deadlines first; the overload banner ignores tasks overdue >7 days.
- One mistyped "actual hours" (2 → 20) no longer rewrites your pace for ever (each ratio is clamped to ⅓×–3×); the report card needs ≥3 tasks before it issues a verdict; "late by" is measured against the real work, not the 15% buffer; the explanation no longer says "have taken" for a blended figure; "0 mores" gone.

**Interface**
- Esc on the "how many hours did it take?" dialog **completed the task anyway** → now a real Cancel; Esc/backdrop abort and the checkbox reverts. Dialog and several inputs were unstyled white boxes in dark mode → styled.
- Large-text and long-text layout: grid tracks can shrink, notes wrap anywhere, task cards stack their buttons on phones, counter grid reflows.
- Light-mode contrast (amber/green/red text and badges, the emerald button, done titles) raised to ≥4.5:1; the auth logo was white-on-white in light mode.
- Settings: header theme toggle and the Dark Mode switch could disagree and Save reverted the theme → synced; switch has a name, `role=switch` and a visible focus ring.
- "Remember me" now actually works (and is off by default); "Forgot password" no longer shows a developer command; the demo Autofill pill works from the keyboard; the empty overload banner no longer shows; keyboard focus survives list refreshes; Edit/Delete buttons announce the task title; dashboard greeting uses the account's timezone; a stale progress response can no longer overwrite a newer one.

**Operations / security**
- Login limiter keyed by SHA-256 and purged by age; name/email/password length caps (an anonymous request could add megabytes to the database and push it past the backup size limit); backup endpoint reports "too large" instead of crashing; limits sized for a shared network (20 wrong tries per account, 150 per address, per 5 min).
- Production now **refuses to boot with `ALLOW_DEMO_SOCIAL_LOGIN=1`** (that switch is passwordless login); `true/yes/on` work for every on/off setting (only `1` used to); `X-Forwarded-Host` no longer trusted; database errors log a traceback.
- `setup.sh`: installs `sqlite3`, writes `FLASK_ENV=production` + `BEHIND_PROXY=1` for hand installs (otherwise the placeholder-secret guard never ran), and after a restart waits for `/healthz` and fails loudly with the log tail if the service is crash-looping. The GCP startup script retries a half-finished install. nginx caches static files 5 min (JS modules import each other without version strings). README: restore recipe no longer needs a missing tool, rollback uses `www-data` and returns to `main`, seed/NAT/`STARTBY_REPO_URL` notes.

## STILL OPEN (decide / do before or after the demo)

**Needs you (not code)**
1. **The tested code is not on `main`.** `origin/main` has none of Phase 2, the GCP layer, the new UI merge or `setup.sh`; README tells the VM to clone the default branch. Commit, merge and push before the freeze (12:00 IST tomorrow). There are also no git tags although the README mentioned `v1.0`.
2. Give each judge their own account if you can — the demo login's attempt budget is shared by everyone behind one network address.
3. `provision.sh` and the whole GCP side have still never run against a real project.

**Known limits (low/medium)**
- Capture: every pasted line becomes a pre-ticked draft (incl. "Dear students"); "within 24 hours"/"in 30 minutes" are read as estimates; "next week Friday", "tomorrow morning" are approximate; a plausible-but-wrong future date inside 3 months is not flagged; "Aaj Tak" (a TV channel) reads as today.
- Reminders: a send is claimed before it is made, so a process killed mid-send loses that one email (at-most-once); no quiet hours; no combined email for a task that is due-soon and red at once.
- Timezone: no banner when the browser's zone differs from the saved zone; JS and Python resolve a DST-gap time one hour apart; legacy zone aliases in the dropdown.
- Accessibility: tap targets 25–36 px (Edit/Delete/chips/checkbox); closed mobile drawer links remain focusable and there is no skip link/`aria-expanded`; filter buttons use `aria-selected` without `role=tab`; toasts last 4 s and errors aren't assertive; "Loading…" stays forever if a card's API call fails; first-run "no tasks" copy; Priority Radar is `ul>div`; no confirmation on capture "Discard" or Calendar "Disconnect"; no `prefers-reduced-motion`; dark-theme input borders ~1.4:1; titles lack `dir="auto"`; 500 tasks render in one page.
- Copy/trust: "Kairo" vs "StartBy"; "Quick Capture" / "Add to Workspace" / "Smart Capture"; Settings claims "PBKDF2-SHA256 Encrypted" (the hash is scrypt) plus filler like "tenant database security status"; Google Fonts CDN breaks the "no CDN" rule; no Content-Security-Policy (templates use inline scripts).
- Ops: `CRON_SECRET` readable by anyone with Scheduler/Tasks viewer role and in `provision.sh` arguments; `INSIGHTS=1` with `ESTIMATES=0` shows "manageable" on real data; two tabs editing one task is last-write-wins; two workers double the effective rate limit; a wrong-region or `http://` `APP_BASE_URL` fails silently.
- Unverified: real-device 320px, Chrome/Safari `Intl` quirks (only Node 18 tested), `gcloud` on the VM image, certbot staging→real behaviour.
