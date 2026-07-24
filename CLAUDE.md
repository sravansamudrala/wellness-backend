# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

FastAPI backend for a personal wellness tracker (skincare routine, reminders, gym, water). Backs the `wellness-tracker` frontend (Vite/React on Vercel — see the CORS allow-list in [app/main.py](app/main.py), which also matches any `http://localhost:<port>` for local dev since Vite auto-increments its port when the default is taken). It is a **multi-user** app: email/password auth via a **custom JWT** scheme, and every *user-owned* row carries a `user_id` foreign key (see **Authentication & per-user data** below). **Shared master data** (the exercise catalog and muscle groups) has **no** `user_id`. Historical note: it began as a single-user app; multi-user was added later, and legacy pre-auth rows were claimed by the first account via `scripts/claim_legacy_data.py`.

## Commands

```bash
# Activate the virtualenv (committed venv/ is the intended env)
source venv/bin/activate

# Run the dev server (set SQL_ECHO=true in .env for SQL logging; off by default)
uvicorn app.main:app --reload

# Install / update deps
pip install -r requirements.txt

# Interactive API docs once running
open http://localhost:8000/docs
```

`DATABASE_URL` must be set in `.env` (loaded by [app/core/config.py](app/core/config.py) via pydantic-settings) — it points at a Supabase PostgreSQL instance via the connection pooler (psycopg 3 driver). The engine sets `pool_pre_ping=True` so connections dropped during Render idle / by the pooler reconnect transparently. Other `.env` settings: `SQL_ECHO` (bool, default off), `LOG_LEVEL` (default `INFO`, see **Logging** below), `AUTH_RATE_LIMIT` (default `5/minute`, see **Authentication** below), and the Web Push vars below (`VAPID_PUBLIC_KEY`, `VAPID_PRIVATE_KEY`, `VAPID_SUBJECT`, `DISPATCH_TOKEN`, `REMINDER_TIMEZONE`). There is no linter config or Makefile in the repo yet.

**Tests**: `pytest` (venv active, from repo root) runs the suite in `tests/` against a **local Docker Postgres** (`docker run --name wellness-test-db -e POSTGRES_USER=test -e POSTGRES_PASSWORD=test -e POSTGRES_DB=wellness_test -p 5433:5432 -d postgres:16`, started once). `tests/conftest.py` points `DATABASE_URL` at it and — critically — **hard-refuses to run at all unless the resolved `DATABASE_URL` contains `localhost`/`127.0.0.1`**. This isn't defensive boilerplate: the suite calls `Base.metadata.drop_all()` on teardown, and this exact gap (a real `DATABASE_URL` left exported in a shell before running `pytest`, which `os.environ.setdefault()` alone doesn't protect against) wiped all production data once — see **Data-loss incident** below. CI (`.github/workflows/tests.yml`) runs the same suite against a throwaway Postgres service container on every push/PR.

## Architecture

Requests flow through three layers, one file per feature in each:

```
app/api/<feature>.py       # APIRouter + endpoint fns — own the DB session lifecycle
  → app/services/<feature>_service.py   # business logic as @staticmethods on a *Service class
    → app/models/<feature>.py           # SQLAlchemy 2.0 ORM (Mapped/mapped_column, DeclarativeBase)
app/schemas/<feature>.py   # Pydantic request/response models (Response uses from_attributes=True)
```

Key conventions to follow when adding features:

- **Session handling is manual, not `Depends`.** Endpoints call `db = SessionLocal()` directly and `db.close()` in a `finally` block (see [app/api/skincare.py](app/api/skincare.py)). Services receive `db` as their first arg and `commit()`/`refresh()` themselves. Match this pattern rather than introducing a FastAPI dependency.
- **Services are stateless classes of `@staticmethod`s** (`SkincareService`, `ReminderService`). No instances are created.
- **Get-or-create is the norm.** `get_today` creates today's `SkincareEntry` if none exists; `ReminderService.get_settings` creates the singleton settings row if the table is empty. `update_*` reuses the getter, so GET/PUT never 404.
- **Registering a feature:** add its model import to [app/models/\_\_init\_\_.py](app/models/__init__.py) (so it's registered on `Base.metadata`) and `include_router` it in [app/main.py](app/main.py).
- **One-file-per-feature is the default** (skincare, reminders, push). A **large** module instead gets a **subpackage per layer** — see the Gym module (`app/models/gym/`, `app/schemas/gym/`, `app/services/gym/`, `app/api/gym/`).

### Database bootstrap & migrations

Two mechanisms coexist:

1. **`Base.metadata.create_all(bind=engine)`** in [app/main.py](app/main.py) still runs at startup — it only ever *creates missing* tables, never `ALTER`s existing ones. This is the fresh-DB bootstrap and is harmless once a table exists.
2. **Alembic is initialized** (`alembic.ini`, [migrations/](migrations/); `migrations/env.py` reads `Base.metadata` + `settings.database_url`). Use it for **any schema change to an existing table** — `create_all` will *not* apply column changes.

The Supabase DB is stamped at the baseline revision `migrations/versions/34f74d57f46b_*` (the full schema). Workflow for a schema change:

```bash
# after editing models
alembic revision --autogenerate -m "describe change"   # review the generated file!
alembic upgrade head
alembic current   # verify
```

Gotchas: the baseline was generated by diffing the models against an empty SQLite DB (`DATABASE_URL="sqlite://" alembic revision --autogenerate`) so it contains the whole schema, then `alembic stamp head` marked the already-populated Supabase DB as being at that revision (no DDL ran there). Prefer **string columns validated by Python enums** over Postgres `ENUM` types — native enums are painful to extend under autogenerate.

## Authentication & per-user data

Custom **JWT** auth (no third-party). Concepts documented in [docs/auth-notes.md](docs/auth-notes.md).

- **Primitives** — [app/core/security.py](app/core/security.py): `hash_password`/`verify_password` (bcrypt), `create_access_token(user_id)`/`decode_token` (PyJWT, HS256, `sub`=user id, `exp`). Secret is `settings.jwt_secret` (**required** env `JWT_SECRET` — app won't boot without it; also set on Render). Deps: `PyJWT`, `bcrypt` in requirements.
- **User model** — [app/models/user.py](app/models/user.py) (`users`: id, email unique, hashed_password, created_at).
- **Auth endpoints** — [app/api/auth.py](app/api/auth.py), prefix `/api/v1/auth`: `POST /register`, `POST /login` (both return `{access_token, token_type}`), `GET /me`. `AuthService` in [app/services/auth_service.py](app/services/auth_service.py) (register/authenticate only — pure; no legacy-claim logic in the hot path).
- **The auth gate** — [app/api/deps.py](app/api/deps.py) `get_current_user` (FastAPI `Depends` + `HTTPBearer`): decodes the `Authorization: Bearer <token>` header → returns `user_id: UUID`, else 401. **Every** protected endpoint adds `user_id: UUID = Depends(get_current_user)` and passes it to its service; services filter every query by `user_id`. The catalog reads are login-gated too but **not** user-scoped (shared) — they use `_user_id: UUID = Depends(get_current_user)` purely as a gate.
- **Per-user tables** (have `user_id` FK): `skincare_entries` (unique swapped `date` → `(user_id, date)`), `reminder_settings` (unique `user_id`), `push_subscriptions`, `reminder_dispatch_log` (unique `(user_id, sent_on, slot)`), `gym_state` (unique `user_id`), `workout_sessions`. Children (`session_exercises`/`session_sets`) inherit ownership via their parent FK. Migration: `migrations/versions/2cae70d68811_*`.
- **Cron dispatch is multi-user** — `PushService.dispatch_due` loops every user with `notifications_enabled` and pushes to *their* subscriptions, deduped per `(user_id, day, slot)`. The `/dispatch?token=` guard is unchanged (cron secret, not user auth).
- **Admin scripts** (`scripts/`, run once locally, `python -m scripts.<name>`): `claim_legacy_data` (adopt NULL-owner rows into an account, conflict-proof), `update_user` (change email/password), `delete_user` (remove a user + owned rows).
- **Rate limiting** ([app/core/rate_limit.py](app/core/rate_limit.py), `slowapi`): `/register` and `/login` are limited to `settings.auth_rate_limit` (env `AUTH_RATE_LIMIT`, default `5/minute`) per client IP. Disabled in tests (`tests/conftest.py` sets `limiter.enabled = False`) since `TestClient` requests all share one fake address. Verified in production that Render/Cloudflare forward the real client IP correctly (`request.client.host` isn't a shared proxy address).

## Logging

[app/core/logging.py](app/core/logging.py) `setup_logging()` is called first thing in `app/main.py`, configuring the root logger's level from `settings.log_level` (env `LOG_LEVEL`, default `INFO`) and a `timestamp LEVEL logger.name: message` format. Each module gets its own logger via `logging.getLogger(__name__)`, not the bare root logger. Currently logs: failed logins (`app/services/auth_service.py`) and push dispatch (a per-run summary plus per-subscription failures, since the cron caller never inspects the response body — `app/services/push_service.py`).

## Skincare endpoints

`SkincareService` (all `@staticmethod`, in [app/services/skincare_service.py](app/services/skincare_service.py)) backs four routes under `/api/v1/skincare` ([app/api/skincare.py](app/api/skincare.py)):

- `GET/PUT /today` — get-or-create today's entry / update its 7 booleans (`SkincareResponse`, `SkincareUpdateRequest`).
- `GET /history` — every entry, newest first, each as a `SkincareHistoryItem` ([app/schemas/skincare_history.py](app/schemas/skincare_history.py)): `date`, `completed`/`total`/`progress` (completion over the 7 booleans), **plus all 7 booleans themselves**.
- `GET /stats` — `SkincareStatsResponse` (in [app/schemas/skincare.py](app/schemas/skincare.py)): `current_streak`, `best_streak`, `total_days`, `average_completion`, and a `message` string. A "100%" day (all 7 booleans true) counts toward a streak; streaks are computed over **consecutive calendar days** and `current_streak` is anchored to today (`get_stats`). `message` is a **rule-based tiered template** (`_streak_message` in the service) — no LLM.

## Water endpoints

`WaterService` (all `@staticmethod`, in [app/services/water_service.py](app/services/water_service.py)) backs five routes under `/api/v1/water` ([app/api/water.py](app/api/water.py)), all per-user:

- `GET /today` — get-or-create today's `WaterEntry` (same get-or-create pattern as skincare's `get_today`).
- `POST /today/add` — add `amount_ml` (`AddWaterRequest`, `gt=0`) to today's entry.
- `GET /history` — every entry, newest first.
- `GET/PUT /settings` — get-or-create `WaterSettings` (`daily_goal_ml` default 2000; `reminders_enabled`, `reminder_start_time`/`reminder_end_time` for hourly push reminders — see **Push notifications** below) / update it (`WaterSettingsUpdateRequest`, `gt=0` on `daily_goal_ml`, all fields required on PUT like `ReminderSettingsUpdateRequest`). Migration: `migrations/versions/70168206a7fa_*`.
- `GET /stats` — `WaterStatsResponse`: `current_streak`, `best_streak`, `total_days`, `average_completion` (0–100 int), `message` (rule-based, same streak-anchored-to-today approach as skincare/gym).

## Push notifications (reminders)

Web Push reminders fire even when the installed PWA is closed: skincare at the user's `morning_time`/`evening_time`, water **hourly** within a configurable window. Flow: the PWA subscribes and POSTs its subscription to the backend; an **external cron** (cron-job.org) hits the dispatch endpoint every ~10 min; the endpoint checks the schedule and pushes via `pywebpush`.

- **Endpoints** ([app/api/push.py](app/api/push.py), prefix `/api/v1/push`): `POST /subscribe` (store the browser subscription); `POST /dispatch?token=<DISPATCH_TOKEN>` (token-guarded; the cron caller) — runs both `PushService.dispatch_due` (skincare) and `PushService.dispatch_water_due` (water) and merges their `{processed_users, sent, errors}` results. `errors` carries per-send failure detail for debugging.
- **`PushService.dispatch_due`** ([app/services/push_service.py](app/services/push_service.py)): if notifications enabled, for each slot due *now* (at/after the reminder time, within a 60-min grace window) and **not already sent today**, push to **all** stored subscriptions and record a dedup row. **One notification per slot per day** — a `ReminderDispatchLog` row keyed `(sent_on, slot)` is the guard; it's written only *after* a successful send, and dead subscriptions (404/410) are auto-deleted.
- **`PushService.dispatch_water_due`**: same dedup/grace-window mechanics, but per-user driven by `WaterSettings.reminders_enabled` and iterates every hour in `[reminder_start_time, reminder_end_time]` rather than two fixed slots. Slot key is hour-specific (`f"water_{hour:02d}"`, e.g. `"water_14"`) so it reuses `ReminderDispatchLog` without a schema change. Skips a user entirely for the day once today's `WaterEntry.amount_ml` already meets `daily_goal_ml`.
- **New tables** (`push_subscriptions`, `reminder_dispatch_log`) are created by `create_all` — no migration needed. (The water reminder *columns* on `water_settings` did need one — see above.)
- **Setup (env, one-time):** `VAPID_PUBLIC_KEY` / `VAPID_PRIVATE_KEY` (VAPID keypair), `VAPID_SUBJECT`, `DISPATCH_TOKEN` (cron secret), `REMINDER_TIMEZONE` (IANA, e.g. `Asia/Kolkata` — Render runs UTC, so this must be set or reminders fire at the wrong hour). The frontend needs `VITE_VAPID_PUBLIC_KEY` = the same public key. Cron: `POST .../api/v1/push/dispatch?token=...` every 10 min.
- **Gotchas learned the hard way:** `VAPID_SUBJECT` must be an **https URL or a real `mailto:` email** — Apple rejects fake domains like `mailto:x@…​.local` with `403 BadJwtToken`. `VAPID_PRIVATE_KEY` must be the **exact** base64url value (a wrong/mangled value fails with `ValueError: Could not deserialize key data` only once a subscription exists to sign for). iOS: push works **only** in the home-screen-installed PWA (16.4+), and permission must be requested from a user gesture.

## Gym module — freestyle Log Workout only (plan/queue system removed 2026-07-24)

A **subpackage per layer** (`app/{models,schemas,services,api}/gym/`) rather than one flat file. Everything mounts under `/api/v1/gym` via an aggregate router in [app/api/gym/\_\_init\_\_.py](app/api/gym/__init__.py) (`include_router`s `catalog`, `workouts`, `insights`). Per-user like the rest of the app: `gym_state` and `workout_sessions` carry `user_id`.

**There used to be a second, plan/queue-based workout system** (`WorkoutPlan`/`PlanDay`/`PlanExercise`, an active-plan cursor, start/log-sets/complete/abandon session lifecycle) alongside the freestyle logger. It was **removed entirely** after an audit confirmed it was fully dead for this app's actual usage: the frontend pages for it were unreachable or permanently showed a broken "no active plan" state, since nothing ever activated a plan. Don't reintroduce plan/queue concepts without deliberately deciding to — this app is single-flow now: create a custom exercise if needed, then log it via `quick_log`.

**6 tables** (models in [app/models/gym/](app/models/gym/)):
- **Catalog (seeded master data):** `muscle_groups`, `exercises` (single-source-of-truth; `image_url` on `Exercise` is currently unused/legacy — the shared reference image lives on `MuscleGroup.image_url` instead, see below).
- **Settings:** `gym_state` — **one row per user** (`WorkoutService.get_state`, get-or-create, unique `user_id`). Holds `unit` (`"kg"`/`"lb"` display pref; storage is always canonical **kg** in `session_sets.weight_kg`) and `rotation_order` (JSON list of muscle-group names, see below).
- **Sessions (source of truth for insights):** `workout_sessions` (status is always `"completed"` — created only via `quick_log`, no in-progress lifecycle; `name` is auto-derived from muscle groups) → `session_exercises` → `session_sets`.

**Catalog**: 8 muscle groups (Chest, Back, Shoulders, Biceps, Triceps, Legs, Core, Cardio) and 48 exercises, seeded from the user's real trainer program via [app/seed/gym_seed.py](app/seed/gym_seed.py) (idempotent upsert-by-name, same as before — `python -m app.seed.gym_seed`). No `Equipment` model/table anymore (was entirely unused — removed alongside the plan/queue system). One shared reference image per muscle group (not per-exercise) is set via `python -m scripts.set_muscle_group_image <Name> --url "..."`.

**Log Workout flow:**
- **Create custom exercise** — `POST /exercises` (`CatalogService.create_exercise`, shared catalog, `is_custom=True`); idempotent by name.
- **Rename / delete** — `PUT`/`DELETE /exercises/{id}`. Delete is **blocked** if the exercise has ever been logged in a session (`SessionExercise.exercise_id` check) — protects historical workout data from a broken/dangling reference; returns 400 with a clear reason rather than a raw FK error.
- **Quick-log** — `POST /sessions/quick-log` (`WorkoutService.quick_log`): logs a list of exercise ids as a completed session, one `is_completed` set each (no weights). **Same-day saves MERGE** into one session (append + dedupe by exercise), auto-named from its muscle groups via `_derive_workout_name` (e.g. "Back, Chest & Cardio").
- Sections in the frontend: muscle groups with exercises, priority-ordered **Back, Chest, Cardio** (`GymLog.tsx`'s `PRIORITY` array — display order only, unrelated to the rotation below).

**Rotation suggestion** ("what should I train next?"): `GymState.rotation_order` is an editable ordered list (default `["Chest", "Biceps", "Back", "Shoulders", "Legs", "Triceps"]` — `Cardio`/`Core` deliberately excluded, logged alongside any day rather than getting their own turn), editable via the existing `GET/PUT /state`. `GET /log/next-category` (`WorkoutService.get_next_log_category`) derives "what's next" purely from session history — **no separate cursor column**: it finds the most recent completed session, gets every rotation category it touched (via `_session_muscle_group_names`, the same join `_derive_workout_name` uses), and advances past the **maximum** rotation-index among them, wrapping around. This matters: a single session touching two categories at once (e.g. "Back & Shoulders") must advance past *both*, not just the first — tested explicitly in `tests/test_gym.py::test_next_log_category_advances_past_all_touched_categories`.

**Insights are derived, no tables** ([insights_service.py](app/services/gym/insights_service.py)), and were already plan-independent before the removal: `/insights/stats` (calendar-day streak anchored to today like skincare, `total_workouts`, `this_week`, `days_since_last`, rule-based `message`), `/insights/volume` (Σ reps×weight_kg, `range=week|month|all`), `/insights/records` (per-exercise max weight / Epley est-1RM / max set volume — sparse for freestyle-only logging since `quick_log` sets carry no weight), `/insights/recovery` (days since each primary muscle trained). Nested session→exercises→sets responses are assembled by [app/services/gym/builders.py](app/services/gym/builders.py).

**AI is Phase 2** and must **consume** existing services (read insights/catalog, log via `WorkoutService`), never own business logic.

## Data-loss incident (2026-07-24) — what happened, why, and the fix

**What happened:** all production data was wiped — every table emptied (users, skincare/water/gym history, the gym catalog) — with no warning.

**Root cause:** a separate working session ran `pytest` while its shell had `DATABASE_URL` already pointing at production (e.g. exported for a one-off manual check, then not unset before running tests). The test suite's session-teardown fixture in `tests/conftest.py` calls `Base.metadata.create_all()` then `Base.metadata.drop_all(bind=engine)` — normally against a disposable local Postgres, but since `DATABASE_URL` was already set, the suite's own safeguard at the time (`os.environ.setdefault("DATABASE_URL", ...)`) silently did nothing — `setdefault` only fills in a value if one **isn't already present**, so an already-exported production URL was left untouched and the suite ran (and tore down) against it. `alembic_version` survived untouched (it's a table Alembic manages outside `Base.metadata`, so `drop_all` can't reach it), which is what made the timeline reconstructable after the fact.

**Recovery:** no backup existed (Supabase free tier has no automatic backups/PITR on this project) — the data was unrecoverable. The gym catalog was rebuilt from scratch (see **Gym module** above); all user accounts and historical skincare/water/workout entries are permanently gone. The affected user re-registered.

**The actual fix**, already in place: `tests/conftest.py` now has a **hard safety check**, not just a default — it inspects the final resolved `DATABASE_URL` after the `setdefault` calls and immediately raises `RuntimeError` (aborting before any table operation) unless the URL contains `localhost` or `127.0.0.1`. This makes the exact failure mode above impossible, regardless of what's already exported in the calling shell. If you ever see this error, run `unset DATABASE_URL` before retrying — don't work around the check itself.

## Current state / gotchas

- `SkincareEntry` uniqueness is now **per user**: `UniqueConstraint(user_id, date)` (was a global `date unique`) — one entry per day *per user*. The skincare habit set is 7 booleans: face_wash, vitamin_c, moisturizer, sunscreen, lipcare, cleanser, evening_moisturizer. When adding/removing a habit, keep **all** of these in sync: the model, `SkincareUpdateRequest`, `SkincareResponse`, `SkincareHistoryItem`, the `completed`/`total` counts in both `get_history` and `get_stats`, and the streak `== 100` check in `get_stats` (hardcoded `/ 7`).
