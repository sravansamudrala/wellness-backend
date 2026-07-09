# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

FastAPI backend for a personal wellness tracker (skincare routine + reminder settings). Backs the `wellness-tracker` frontend (Vite/React on Vercel — see the CORS allow-list in [app/main.py](app/main.py)). This is a **single-user** app: there is no auth and no `user_id` on any table — each table holds one logical record per key (one skincare entry per calendar day, one global reminder-settings row).

## Commands

```bash
# Activate the virtualenv (committed venv/ is the intended env)
source venv/bin/activate

# Run the dev server (SQL echo is on by default in the engine)
uvicorn app.main:app --reload

# Install / update deps
pip install -r requirements.txt

# Interactive API docs once running
open http://localhost:8000/docs
```

`DATABASE_URL` must be set in `.env` (loaded by [app/core/config.py](app/core/config.py) via pydantic-settings) — it points at a PostgreSQL instance (psycopg 3 driver). There is no test suite, linter config, or Makefile in the repo yet.

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
- **Registering a feature:** add its model import to [app/models/\_\_init\_\_.py](app/models/__init__.py) (so `Base.metadata.create_all` sees it) and `include_router` it in [app/main.py](app/main.py).

### Database bootstrap

Tables are created at import time via `Base.metadata.create_all(bind=engine)` in [app/main.py](app/main.py:25) — **there are no migrations run**. `alembic` is listed in requirements.txt but is not initialized (no `alembic.ini`, no `migrations/`). Changing a model's columns will **not** alter an existing table; you must drop/recreate or wire up Alembic. New models only need to be imported before `create_all` runs.

## Skincare endpoints

`SkincareService` (all `@staticmethod`, in [app/services/skincare_service.py](app/services/skincare_service.py)) backs four routes under `/api/v1/skincare` ([app/api/skincare.py](app/api/skincare.py)):

- `GET/PUT /today` — get-or-create today's entry / update its 7 booleans (`SkincareResponse`, `SkincareUpdateRequest`).
- `GET /history` — every entry, newest first, each as a `SkincareHistoryItem` ([app/schemas/skincare_history.py](app/schemas/skincare_history.py)): `date`, `completed`/`total`/`progress` (completion over the 7 booleans), **plus all 7 booleans themselves**.
- `GET /stats` — `SkincareStatsResponse` (in [app/schemas/skincare.py](app/schemas/skincare.py)): `current_streak`, `best_streak`, `total_days`, `average_completion`. A "100%" day (all 7 booleans true) counts toward a streak.

## Current state / gotchas

- `SkincareEntry.date` is `unique=True` (one entry per day). The skincare habit set is 7 booleans: face_wash, vitamin_c, moisturizer, sunscreen, lipcare, cleanser, evening_moisturizer. When adding/removing a habit, keep **all** of these in sync: the model, `SkincareUpdateRequest`, `SkincareResponse`, `SkincareHistoryItem`, the `completed`/`total` counts in both `get_history` and `get_stats`, and the streak `== 100` check in `get_stats` (hardcoded `/ 7`).
