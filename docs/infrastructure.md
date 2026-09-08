# Deployed Infrastructure

Reference for every external service this app depends on in production: what it's for, where it lives, and what to check first when something breaks. Values (API keys, passwords) are never recorded here — only which env var holds them and where they're set. Local-only file (gitignored, like `TODO.md`) — not committed to the repo.

## Overview

```
Vercel (frontend, static)  →  Render (backend API, Singapore)  →  Supabase (Postgres, ap-southeast-1)
                                        ↓                              ↑
                                  SendGrid (email)          cron-job.org (push reminders, every ~10 min)
```

## Backend hosting — Render

- **Service**: `wellness-backend` (web service)
- **Region**: **Singapore** — migrated here 2026-07-28 from Oregon (US West) specifically to sit next to Supabase's `ap-southeast-1` region. The Oregon↔Singapore round trip was adding a flat ~1-1.5s tax to every DB-backed request; same-region now measures ~0.2-0.3s. See `TODO.md`'s "API performance" entry for the full story. **Render does not support changing an existing service's region in place** — moving meant creating a brand-new service and cutting the frontend over to its URL, not a settings toggle.
- **Production URL**: `https://wellness-backend-r1pr.onrender.com`
- **Old URL (decommissioned)**: `https://wellness-backend-i1hv.onrender.com` (Oregon) — deleted after the migration was verified stable. If this URL is ever seen referenced anywhere (old bookmarks, stale docs, a forgotten env var), it's dead.
- **Build command**: `pip install -r requirements.txt`
- **Start command**: `uvicorn app.main:app --host 0.0.0.0 --port $PORT` (single worker, no `--workers` flag — relevant if ever revisiting in-memory caching schemes, since there's currently no cross-process state to worry about)
- **Deploy trigger**: auto-deploys on push to `main` (every feature branch in this repo is merged via PR into `main`, per this project's workflow — see `CLAUDE.md`)
- **Root directory**: repo root (no monorepo subfolder)
- **Known limitation**: Render **blocks all outbound SMTP** (confirmed empirically — see `docs/auth-notes.md` and the SendGrid section below). Any future email-sending feature must use an HTTP API provider, never raw SMTP.

### Environment variables (Render → Environment tab)

| Variable | Purpose | Required? |
|---|---|---|
| `DATABASE_URL` | Supabase Postgres connection string (psycopg 3 driver) | Yes |
| `JWT_SECRET` | Signs/verifies auth JWTs | Yes |
| `SENDGRID_API_KEY` | Sends password-reset emails via SendGrid's HTTP API | Yes (reset flow silently no-ops without it) |
| `MAIL_FROM` | Must be a SendGrid-verified Single Sender — currently `hello.wellnesstracker@gmail.com` | Yes |
| `FRONTEND_URL` | Builds the password-reset link in the email (`{FRONTEND_URL}/reset-password?token=...`) — set to the production Vercel URL | Yes |
| `VAPID_PUBLIC_KEY` / `VAPID_PRIVATE_KEY` / `VAPID_SUBJECT` | Web Push (skincare/water reminders) | Yes, for push to work |
| `DISPATCH_TOKEN` | Shared secret guarding `/api/v1/push/dispatch` — the cron caller | Yes |
| `REMINDER_TIMEZONE` | IANA tz (e.g. `Asia/Kolkata`) reminder times are expressed in — Render itself runs UTC | Yes, else reminders fire at the wrong hour |
| `ENABLE_API_DOCS` | Set to `false` in production to hide `/docs`/`/redoc`/`/openapi.json` | Recommended `false` in prod |
| `AUTH_RATE_LIMIT` | Override the default `10/minute` on `/register`/`/login` | Optional |
| `PASSWORD_RESET_RATE_LIMIT` | Override the default `3/hour` on `/forgot-password` | Optional |
| `PASSWORD_RESET_TOKEN_EXPIRE_MINUTES` | Override the default 45-minute reset-link expiry | Optional |
| `LOG_LEVEL` / `SQL_ECHO` | Logging verbosity | Optional |
| `GROQ_API_KEY` | Powers AI-generated skincare/water encouragement messages via Groq's chat-completions API | Optional (unset falls back to rule-based messages) |
| `GROQ_MODEL` | Groq model ID for the above. Set explicitly to `qwen/qwen3.8-27b` on both `wellness-backend-r1pr` and `wellness-backend-l05j` (2026-08-26) after Groq decommissioned the previous default, `llama-3.1-8b-instant` (shutdown 2026-08-16). An intermediate replacement, `openai/gpt-oss-20b`, was tried and rejected — it's a reasoning model that needed `max_tokens` raised well above the default 30 to avoid returning empty content. `qwen/qwen3.8-27b` needs no such workaround and, being a distinct model ID from `GROQ_VISION_MODEL`'s `qwen/qwen3.6-27b`, doesn't share its rate-limit pool. Check [console.groq.com/docs/deprecations](https://console.groq.com/docs/deprecations) if messages start failing again | Optional (code default in `app/core/config.py` matches this value) |
| `GROQ_VISION_MODEL` | Groq vision-capable model ID used by the food-photo calorie estimator (`app/services/food_vision_service.py`) — separate feature and separate Groq rate-limit pool from `GROQ_MODEL` above, since it's a different model ID. Set explicitly to `qwen/qwen3.6-27b` on both `wellness-backend-r1pr` and `wellness-backend-l05j` (2026-08-26), matching the code default (unchanged, not affected by the `llama-3.1-8b-instant` deprecation above) | Optional (code default in `app/core/config.py` matches this value) |

Deprecated/unused: `GMAIL_ADDRESS`, `GMAIL_APP_PASSWORD` — leftover from the abandoned Gmail-SMTP attempt (see the SendGrid section below for why that didn't work). Safe to remove from Render's env if still present; the code no longer reads them.

## Database — Supabase (Postgres)

- **Region**: `ap-southeast-1` (Singapore) — the reason Render was moved to match.
- **Connection**: direct connection (`db.<project-ref>.supabase.co:5432`), psycopg 3 driver, `pool_pre_ping=True` so connections dropped during idle periods reconnect transparently. (Despite `CLAUDE.md` describing this as "via the connection pooler," the actual `DATABASE_URL` in use is the direct-connection form, not a Supavisor pooler URL — worth reconciling if that doc is ever revisited.)
- **Backups**: none on the current (free) Supabase tier — see `CLAUDE.md`'s Data-loss incident section. There is no automatic recovery path if data is destroyed; `tests/conftest.py` has a hard safety check specifically to prevent a repeat.
- **Migrations**: Alembic, run manually (`alembic upgrade head`) against whichever `DATABASE_URL` is active — there's no CI/CD-automated migration step on deploy today (a Render "Pre-Deploy Command" set to `alembic upgrade head` was discussed as a future improvement but not yet configured).
- **Shared with local dev**: there is no separate local/staging database — `.env`'s `DATABASE_URL` used by a local `uvicorn --reload` process points at this same production instance. See `CLAUDE.md`'s `create_all()` gotcha.

## Frontend hosting — Vercel

- **Production domains** (both live, same deployment — confirmed identical JS bundle hash): `https://aiwellnesstracker.vercel.app` (current project name) and `https://wellness-tracker-tan.vercel.app` (original pre-rename domain, still a live alias). The project was renamed from `wellness-tracker` to `aiwellnesstracker` at some point without the backend's CORS config being updated to match — this broke login with a CORS error on 2026-07-29 until `app/main.py`'s `allow_origin_regex` was widened to accept both prefixes. **If the project is ever renamed again, update that regex.**
- **Framework**: Vite/React, deployed as a static build
- **Deploy trigger**: auto-deploys on push (production branch + preview deployments for other branches/PRs — this is why the backend's CORS config uses a regex matching Vercel URL patterns rather than a fixed list, see `app/main.py`)
- **Environment variables** (Vercel → Project → Environment Variables):
  - `VITE_API_URL` — points at the backend; must be updated (and the app **redeployed**, since Vite bakes this into the build at compile time, not runtime) whenever the backend's URL changes, as happened during the Render region migration.
  - `VITE_API_URL_FALLBACK` — backup Render account, see "Backup backend account" below. Set here in Vercel's dashboard, which takes precedence over the repo's committed `.env.production` at build time (Vite: real env vars beat `.env` file values) — keep both in sync anyway so a local/CI build without dashboard access doesn't silently fall back to a stale URL, which is exactly what happened with the old `i1hv` URL before this was caught.
  - `VITE_VAPID_PUBLIC_KEY` — must match the backend's `VAPID_PUBLIC_KEY`.
- **Vercel Analytics**: added 2026-07-29, `<Analytics />` from `@vercel/analytics/react` mounted at the app root (`src/main.tsx`), not inside the routed component tree.

## Email — SendGrid

- **Why SendGrid and not Gmail SMTP**: the first attempt used Gmail SMTP with a dedicated account (`hello.wellnesstracker@gmail.com`) and an App Password. This **cannot work from Render** — Render blocks outbound SMTP entirely (confirmed: port 465/`SMTP_SSL` failed immediately with "Network is unreachable"; STARTTLS/587 with IPv4 forced instead *timed out*, the signature of a firewall drop, ruling out a DNS/IPv6-routing theory). Any SMTP-based approach is a dead end on this host, regardless of credentials.
- **Current setup**: SendGrid's HTTP API (`https://api.sendgrid.com/v3/mail/send`), called via plain `requests.post` — ordinary HTTPS, which Render doesn't block.
- **Sender identity**: `hello.wellnesstracker@gmail.com`, verified as a SendGrid **Single Sender** (Settings → Sender Authentication). No domain is owned by this project, which is why Single Sender Verification was used instead of full domain verification (what Resend/SendGrid would otherwise prefer) — this only requires clicking a confirmation link SendGrid emails to that address, no DNS records.
- **The Gmail account itself** (`hello.wellnesstracker@gmail.com`) is *only* used as this verified identity now — it is no longer used for actual SMTP sending. The 2-Step-Verification + App Password set up for the abandoned SMTP attempt are unused leftovers.
- **API key**: `SENDGRID_API_KEY`, set in Render's env. Generated from SendGrid → Settings → API Keys.

## Push notification dispatch — cron-job.org

- Hits `POST https://wellness-backend-r1pr.onrender.com/api/v1/push/dispatch?token=<DISPATCH_TOKEN>` every ~10 minutes.
- **Must be updated whenever the backend URL changes** — this was one of the follow-up steps after the Render region migration (already done).
- The endpoint itself dedupes sends per `(user_id, day, slot)`, so a missed or delayed cron tick doesn't cause duplicate notifications, only a delayed one.

## wellness-aiwt keep-alive — cron-job.org

- Added 2026-08-14 after real production incidents: the water-reminder dispatch above only calls `wellness-aiwt` roughly once per hour (per due user), but Render's free tier spins a service down after 15 min idle — so `wellness-aiwt` was asleep on every hourly call, and the front proxy returned `429 Too Many Requests` for the first request(s) during wake-up, which `wellness-backend`'s fallback logic (`app/services/aiwt_service.py`) treated as failure and used the static message instead of a generated one. Confirmed from real Render logs, twice, an hour apart (06:30 and 06:30+1h UTC, 2026-08-14).
- Fix: a second `cron-job.org` job hits `GET https://wellness-aiwt.onrender.com/` every ~10 minutes, same pattern as the dispatch job above. This alone is enough to keep it warm — `wellness-aiwt`'s model session is a lazy-loaded singleton (`inference.py`'s `_state["loaded"]`), so it doesn't need to be hit on `/v1/generate` specifically; it loads once on the first real dispatch call and stays loaded as long as the process doesn't spin down.
- Belt-and-suspenders: `aiwt_service.py` also retries up to 3 attempts (3s delay) specifically on a 429 response before falling back to the static message, in case the keep-alive ping ever has a gap.

## Backup backend account — Render (added 2026-08-24)

Two incidents hit the primary account (`wellness-backend-r1pr`, and its paired `wellness-aiwt` service) the same day:

1. **Shared workspace usage-limit exhaustion**: Render's free tier gives the whole workspace a pool of 750 instance-hours/month. `wellness-aiwt`'s 24/7 keep-alive cron (see the section above) plus `wellness-backend`'s necessary 24/7 dispatch-cron uptime together burned through it — measured at 738.92/750 hours before the reset. Not yet fixed at the root (dropping the `wellness-aiwt` keep-alive would fix it, tracked as a follow-up, not yet done as of this writing).
2. **Tampered Start Command**: `wellness-backend`'s Render Start Command was found set to `sudo delete web service wellness-backend` — not something in this repo (Start Command is dashboard-only config, no `render.yaml`/`Procfile` sets it), so it was typed/pasted directly into the dashboard by someone/something with account access. Harmless in effect (`sudo` doesn't exist in the container, and the literal text isn't a real deletion command either way), but the service couldn't boot until reverted to `uvicorn app.main:app --host 0.0.0.0 --port $PORT`. **Root cause (who/what changed it) was not investigated** — worth checking Render's account activity/audit log and rotating credentials if it recurs.

**Backup services created as a result:**
- `wellness-backend-l05j.onrender.com` — same Supabase database (no migration needed, Supabase is external to Render), same `JWT_SECRET`/VAPID keypair as `r1pr` (confirmed identical, required for sessions/push to survive a failover).
- `wellness-aiwt-iau5.onrender.com` — no env vars needed (only `RENDER_GIT_COMMIT`, which Render sets automatically); model artifacts are committed directly in that repo, so a fresh deploy just works. `AIWT_SERVICE_URL` on the backup backend needs to be pointed at this once wired up (not yet done as of this writing).

**Frontend failover** (`wellness-tracker/src/services/api.ts`): the shared axios instance now automatically fails over from `VITE_API_URL` to `VITE_API_URL_FALLBACK` when the primary is unreachable, in three tiers:
1. Render's own edge returns a specific signature (`x-render-routing: no-server` header) when an account is suspended/deleted — detected directly, skips straight to the backup rather than wasting a retry.
2. Ordinary cold-start-shaped failures (timeout, network error, 502/503/504) get one same-host retry first, before falling back.
3. Once either path confirms the primary is down, a module-level flag makes every later request in that browser tab/session go straight to the backup — avoiding a repeated double round-trip on every call for the rest of the outage. A fresh page load clears the flag, so it self-heals automatically once the primary is restored.

**Still open:**
- Drop (or don't recreate) `wellness-aiwt`'s keep-alive cron so the usage-limit issue doesn't recur monthly.
- Point `AIWT_SERVICE_URL` on `wellness-backend-l05j` at `wellness-aiwt-iau5`.

**Resolved (2026-09-08) — dispatch cron redundancy decision:** deliberately **not** running two active dispatch cron jobs in parallel — that would double the cron traffic's contribution to the shared 750-instance-hour pool, working against the exact root cause in incident #1 above. Instead:
- **Primary cron job** (cron-job.org) stays pointed at `r1pr` only, active as normal.
- **A second dispatch job targeting `l05j` exists but is kept disabled/paused** at all times — same URL pattern (`POST https://wellness-backend-l05j.onrender.com/api/v1/push/dispatch?token=<DISPATCH_TOKEN>`), same schedule, just toggled off in cron-job.org's dashboard.
- **During an incident**, manually enable the `l05j` job (and optionally pause the `r1pr` one if it's confirmed fully down, to avoid wasted failed-attempt noise in logs). This keeps the backup's Render instance-hours usage at zero during normal operation, at the cost of requiring a manual step to activate failover for the push-dispatch cron specifically (unlike the frontend's fully automatic 3-tier failover above, which needs no manual intervention).

## Incident log

- **2026-09-08 — water reminders not arriving, dispatch cron found disabled.** User reported enabled water reminders not firing. Traced to the `r1pr` dispatch cron job on cron-job.org being disabled — root cause of *why* it got disabled not confirmed (possibly a repeat of the instance-hours exhaustion pattern from 2026-08-24, possibly manually paused and forgotten; worth checking cron-job.org's own job history/execution log next time before re-enabling blind). Manually re-enabled the job; confirmed `wellness-backend-r1pr` responding normally afterward (`/` → 200, ~0.3s, no cold-start delay) and a real push notification was subsequently received. No code change was needed — this was purely an external cron-configuration state issue. Action item from this incident: the "pre-created but disabled backup dispatch job" plan above, so a future occurrence has a faster, well-rehearsed manual failover instead of only "re-enable and hope."

## Quick reference — "the primary Render account seems down"

1. Check for Render's own suspension signature directly: `curl -sD - <url>/ | grep -i x-render-routing` — a value of `no-server` means the *account/service* is gone (deleted or suspended), not a normal app-level error. A real app 404 has `x-render-origin-server: uvicorn` instead and a JSON body, not plain text.
2. If suspended, the frontend should already be failing over automatically (see "Backup backend account" above) — confirm by checking which `baseURL` a failing request actually hit in the browser Network tab.
3. Check Render's workspace Usage page (Account Settings → Usage) for the free-tier instance-hours pool — a shared 750-hour/month cap across *all* free services in the workspace, not per-service. This doesn't show the reset date; check Billing → Invoices for the next billing/reset date instead.
4. If the Start Command looks wrong/unfamiliar in the dashboard, treat it as a possible credential compromise, not a typo — check the account's activity/audit log before just fixing and moving on.

## Source control — GitHub

- **Repos**: `sravansamudrala/wellness-backend`, `sravansamudrala/wellness-tracker`
- **Workflow**: every change (however small) goes on its own feature branch cut from `main`, then merged via a GitHub PR — never committed directly to `main`. This project deliberately avoids the GitHub CLI (`gh` is not installed locally as of this writing) — PRs are created by visiting the URL git prints after `git push -u origin <branch>` and merged manually in the GitHub UI.
- No CI-driven deploy gate beyond the test suite (`.github/workflows/tests.yml`) — Render/Vercel deploy independently on push to `main`, not gated on CI passing.

## Quick reference — "it's slow again, what do I check?"

1. Is this the very first request after idle time? Render's free tier spins down and cold-starts — a single slow request after inactivity is expected, not a regression.
2. Compare against an **unauthenticated** endpoint (`/` or `/health/db`) at the same moment — if those are *also* slow, it's general network/Render conditions, not application code (this exact reasoning caught false "regressions" during the session-invalidation benchmark on 2026-07-28).
3. Check Render and Supabase are still in the same region — if either was ever recreated without checking, this is the single highest-impact thing to get wrong (see the Render section above).
4. Check Render's own status page / dashboard for platform-wide incidents before assuming it's this app's code.

## Quick reference — "CORS/login broke after a frontend change"

The Vercel project rename incident (2026-07-29) is the template for this failure mode: if the frontend gets a new domain (rename, custom domain, new project) and login suddenly fails with a browser CORS error (often showing as inconsistent 400s or "no status" in the Network tab, or Chrome's "invalid or missing response headers" message), check `app/main.py`'s `allow_origin_regex` first — it needs to match the *exact* new domain pattern. `curl`-based testing will never catch this, since `curl` doesn't enforce CORS at all — this must be tested from an actual browser, or simulated with `curl -i -X OPTIONS ... -H "Origin: <domain>"` to inspect the preflight response headers directly.