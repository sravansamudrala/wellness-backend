# Smart Meter Slab Optimization — Implementation Plan

Status: ready to execute. Translates the three authoritative documents below into a concrete, file-by-file build sequence. Introduces **no new product decisions** — anywhere this plan states a specific value, field name, or algorithm step, it is quoting a spec, not deciding one.

Source of truth, in this order:
1. [`feature-spec.md`](./feature-spec.md) — product requirements, acceptance criteria.
2. [`backend-spec.md`](./backend-spec.md) — backend algorithm, data contract, business rules.
3. [`frontend-spec.md`](./frontend-spec.md) — UI integration, frontend data contract.

This document **does not** modify application code and does not implement the feature — it is the plan for a future set of PRs. No migration is created by this document (§7 confirms none is needed).

---

## 1. Repository Inspection Findings (this revision)

Verified directly against the current repo state before writing this plan:

- **Migrations are real and actively used here** — `alembic.ini` + `migrations/versions/` contain genuine schema-changing migrations (e.g. `57d5680c4a0a_add_electricity_tracker_and_feature_flags.py`, `17f0c5f350b6_add_meter_shares_table.py`). `CLAUDE.md`'s "Database bootstrap & migrations" section is explicit: `Base.metadata.create_all()` (called on every app startup, `app/main.py:59`) silently creates **brand-new tables** with no migration needed, but **any change to an existing table's columns requires Alembic** — `create_all` cannot alter columns. This feature adds zero new tables and zero new/changed columns on any existing table, so by this project's own documented rule, no migration is required (§7 restates this as a confirmation, not a new claim).
- **No `.env.example` or `render.yaml`/`Procfile` in this repo** — environment configuration is managed outside the repo (Render dashboard / local `.env`). This plan's new `Settings` fields need no corresponding repo file update; §6 covers what (if anything) an operator would set.
- **No frontend test runner exists** (`wellness-tracker/package.json` has no `vitest`/`jest`/`@testing-library/react`, no `*.test.*` files) — confirmed unchanged since `frontend-spec.md` §19 documented this. §11 below plans around that reality rather than silently introducing test infrastructure as a side effect of this feature.
- All backend/frontend file contents this plan references (`app/core/config.py`, `app/services/push_service.py`, `app/services/electricity_insights_service.py`, `app/schemas/electricity.py`, `app/api/push.py`, `src/pages/Electricity.tsx`, `src/services/electricityApi.ts`, `src/index.css`) were read in full during the drafting of `backend-spec.md`/`frontend-spec.md` and re-checked for this plan — no drift found.

No concerns found that would change any decision already made in the three specs.

---

## 2. Backend Files to Create

| File | Contents |
|---|---|
| `app/services/meter_slab_recommendation_service.py` | The shared calculation module. Exports `evaluate_switch_recommendation(db, user_id, today) -> SwitchRecommendation \| None` (backend-spec §1, §16.2) plus private helpers for §5-§11's steps (billing-period estimation, rate/projection, slab/buffer math, decision logic, explanation text). No DB writes, no push calls, no `ReminderDispatchLog` access (backend-spec §1, §14, §16.3). |
| `tests/test_meter_slab_recommendation.py` | New test module, backend-spec §20's tests (including AC12b's duplicate-billing-dates regression, added in this revision) + edge cases. Follows `tests/test_electricity.py`'s fixture/factory conventions. |

Suggested shape for the return type (a plain dataclass — **not** a SQLAlchemy model, see §16 risk):

```python
@dataclass
class SwitchRecommendation:
    active_meter_id: UUID
    active_meter_label: str
    standby_meter_id: UUID
    standby_meter_label: str
    active_cumulative_units: float
    active_next_slab_min: float
    active_operational_threshold: float
    standby_cumulative_units: float
    standby_next_slab_min: Optional[float]
    standby_operational_threshold: Optional[float]
    recommended_switch_date: date
    explanation: str
```

Field names match `backend-spec.md` §16.1's table exactly, so `SlabRecommendationResponse` (§3 below) can be built with `SlabRecommendationResponse(**asdict(recommendation))` or field-by-field — no renaming/translation layer needed between the calculation result and the API/dispatch consumers.

---

## 3. Backend Files to Modify (additive only)

| File | Change | Spec reference |
|---|---|---|
| `app/core/config.py` | Add 4 new `Settings` fields: `meter_slab_min_evaluation_days: int = 10`, `meter_slab_safety_buffer_units: float = 2`, `meter_slab_default_billing_period_days: int = 30`, `meter_slab_min_billing_intervals_for_estimate: int = 2` — each with a one-to-two-line comment, following the existing convention (e.g. `reminder_timezone`, `dispatch_token`). | backend-spec §22 |
| `app/services/push_service.py` | Add `METER_SLAB_MESSAGE = ("⚡ Consider switching meters", "Your usage is approaching the next slab. Switching your active meter may help keep one meter within the lower usage slab.")` (module constant, alongside `SLOT_MESSAGES`/`WATER_MESSAGE`). Add `PushService.dispatch_meter_slab_recommendation(db) -> dict` static method. | backend-spec §1, §4, §12-§14, §17-§19 |
| `app/api/push.py` | In `dispatch()`, add `meter_slab_result = PushService.dispatch_meter_slab_recommendation(db)` and merge its three keys into the existing three-key sum/concat, exactly as `skincare_result`/`water_result` already are. | backend-spec §17 |
| `app/schemas/electricity.py` | Add `SlabRecommendationResponse` (12 fields, backend-spec §16.1's table). Add `slab_recommendation: Optional[SlabRecommendationResponse] = None` to `InsightsResponse`. | backend-spec §16.1 |
| `app/services/electricity_insights_service.py` | In `get_insights(db, user_id)`, after resolving `active_meter_id`/building the `meters` list, call `evaluate_switch_recommendation(db, user_id, local_today())` and include the result (or `None`) as `"slab_recommendation"` in the returned dict. Add the one new import (`from app.core.timezone import local_today` and `from app.services.meter_slab_recommendation_service import evaluate_switch_recommendation`). No change to the function's existing per-meter loop or any existing field. | backend-spec §16.2 |

**Not modified**: `app/api/electricity.py` (the route's `response_model=InsightsResponse` and body are already correct once `InsightsResponse` gains the field and `get_insights` populates it — zero route-level changes needed), `app/models/electricity.py`, `app/models/reminder_dispatch_log.py`, `app/models/feature_flag.py`, `app/api/deps.py`, `app/services/electricity_service.py`, `ElectricitySwitchMeter`'s backend counterpart (`create_switch_event`) — feature-spec's Out of Scope list is respected by construction.

---

## 4. Frontend Files to Modify (additive only)

| File | Change | Spec reference |
|---|---|---|
| `src/services/electricityApi.ts` | Add `SlabRecommendation` interface (12 fields, camelCase-free — matches backend snake_case exactly, per this file's existing convention). Add `slab_recommendation: SlabRecommendation \| null;` to the `InsightsResponse` interface. No function signature changes — `getInsights()` is untouched. | frontend-spec §3, §4 |
| `src/index.css` | Add `.electricity-recommendation-card`, `.electricity-recommendation-compare`, `.electricity-recommendation-meter-label`, `.electricity-recommendation-units`, `.electricity-recommendation-date` — reusing existing custom properties (`--electricity-copper`, `--electricity-copper-bg`, `--card-bg`, `--border`, `--shadow`); no new color/design token. | frontend-spec §6 |
| `src/pages/Electricity.tsx` | Insert the conditional recommendation-card JSX (frontend-spec §6) immediately after `<h2>⚡ Electricity</h2>` and before `meters.map(...)`, gated on `!loading && !error && recommendation` (reusing the existing `meters`/`loading`/`error` state already fetched by the existing `getInsights()` call — no new `useEffect`, no new state variable beyond destructuring `slab_recommendation` from the existing response). | frontend-spec §5, §6, §11, §13, §14 |

**Not modified**: `src/pages/ElectricitySwitchMeter.tsx` (zero changes — frontend-spec §10), `src/pages/ElectricityLogReading.tsx`, `src/pages/Dashboard.tsx`, `src/components/settings/ElectricitySharingSection.tsx`, `src/App.tsx` (no new route), `public/push-sw.js` (no changes in this plan's scope — see §16 risk on the deferred deep-link enhancement), `src/services/pushApi.ts`.

---

## 5. Frontend Files to Create

**None.** Per frontend-spec §2/§5's explicit minimal-footprint design, this feature is entirely additive within existing files — no new component, no new page, no new route, no new service module. (A new `*.test.tsx` file would be created only if/when a test framework is bootstrapped — frontend-spec §19 treats that as a separate, out-of-scope infra decision, not part of this feature's file list.)

---

## 6. Configuration Changes

**`app/core/config.py`** — the 4 fields listed in §3 above, added to the `Settings` class body (exact position: anywhere among the other fields; suggest grouping them together with a one-line section comment, matching how e.g. the SendGrid fields are grouped).

**Environment** — **no `.env`/Render change is required to deploy.** All 4 fields have defaults that reproduce the exact values `backend-spec.md` specifies (`10`, `2`, `30`, `2`), so behavior is identical with zero environment changes. If an operator later wants to tune one without a deploy, the env var names are the uppercased field names (`METER_SLAB_MIN_EVALUATION_DAYS`, `METER_SLAB_SAFETY_BUFFER_UNITS`, `METER_SLAB_DEFAULT_BILLING_PERIOD_DAYS`, `METER_SLAB_MIN_BILLING_INTERVALS_FOR_ESTIMATE`) — standard pydantic-settings case-insensitive matching, same as every other field in this `Settings` class; no `env_prefix`/`alias` config needed since none of the existing fields use one.

**Frontend** — no new `VITE_*` env var needed (no new API base URL, no new feature flag key — reuses `electricity_tracker`).

---

## 7. Database Migration Confirmation — None Required

Confirmed by inspection, not assumed:

- Zero new tables. Zero new or changed columns on `meters`, `meter_readings`, `meter_switch_events`, `meter_shares`, `slab_thresholds`, `reminder_dispatch_log`, or `feature_flags`.
- The only new "data" this feature writes is a value convention inside the existing `ReminderDispatchLog.slot` `String` column (`meter_slab_recommendation_{anchor_reading_id}`) — a value, not a schema change.
- Per `CLAUDE.md`'s own migration rule (quoted in §1), a schema change to an *existing* table is what would require Alembic; this feature makes none. `Base.metadata.create_all()` (already run on every startup) has nothing new to create either, since no new `Base`-derived model is introduced.
- `SwitchRecommendation` (§2) is a plain Python `dataclass`, not a SQLAlchemy model — it must never be added to `app/models/` or imported by anything that calls `Base.metadata.create_all`/`alembic revision --autogenerate`, or it would spuriously trigger exactly the kind of migration this plan confirms is unnecessary (flagged again in §16 as a risk).

**No migration file is created by this plan or should be created during implementation.**

---

## 8. Existing Functions/Components Reused (consolidated)

| Layer | Reused | From |
|---|---|---|
| Backend | `accessible_meter_ids`, `resolve_active_meter_id`, `compute_cumulative`, `bracket_for`, `_next_slab_min` | `app/services/electricity_insights_service.py` |
| Backend | `Meter`, `MeterReading`, `MeterSwitchEvent`, `MeterShare`, `SlabThreshold`, `FeatureFlag`, `ReminderDispatchLog` models | `app/models/` (read-only; `ReminderDispatchLog` also written by the existing convention) |
| Backend | `PushService.send_to_user` | `app/services/push_service.py` |
| Backend | `dispatch_due`/`dispatch_water_due`'s loop/dedup/send/log control-flow shape | `app/services/push_service.py` (pattern reused, code not touched) |
| Backend | `app/core/timezone.py`'s `local_today()`/`local_now()` | new code depends on this, existing file untouched |
| Backend | `require_feature("electricity_tracker")` router dependency | `app/api/electricity.py` (already covers the read path; dispatch path uses a direct `FeatureFlag` query instead, per backend-spec §18) |
| Frontend | `getInsights()`, `SkeletonCard`, `.status-error`, `.electricity-meter-card`/`-badge-active`/`-badge-standby`/`-nudge`, `.electricity-btn-primary`, `hasFeature("electricity_tracker")` | `src/services/electricityApi.ts`, `src/components/Skeleton.tsx`, `src/index.css`, `src/context/AuthContext.tsx` |
| Frontend | The existing `Switch Meter` `<Link>`/route (`/electricity/switch`) and `ElectricitySwitchMeter.tsx`'s own active/standby derivation | `src/pages/Electricity.tsx`, `src/pages/ElectricitySwitchMeter.tsx` — **zero changes to either's switch mechanism** |

---

## 9. Implementation Order and Dependencies

Numbered so each step's dependencies are already satisfied by an earlier step. Steps within the same phase have no dependency on each other and can be done in either order (or by different people in parallel).

**Phase 0 — Config (unblocks everything)**
1. `app/core/config.py` — add the 4 `Settings` fields (§3, §6). Nothing else depends on this failing to exist; do it first so every later step can reference `settings.meter_slab_*` immediately.

**Phase 1 — Shared calculation module (unblocks both integration points)**
2. `app/services/meter_slab_recommendation_service.py` — implement `evaluate_switch_recommendation` and its helpers (backend-spec §5-§11), reading the Phase 0 settings.
3. `tests/test_meter_slab_recommendation.py` — write and pass the calculation-only tests that don't require dispatch or the read path yet: #1-#18, #35 (backend-spec §20). Run these **before** starting Phase 2/3 — a bug caught here is a bug that would otherwise be caught twice (once per caller) or missed if only one caller is tested.

**Phase 2 — Dispatch integration (depends on Phase 1 only; independent of Phase 3)**
4. `app/services/push_service.py` — add `METER_SLAB_MESSAGE` and `dispatch_meter_slab_recommendation(db)`.
5. `app/api/push.py` — wire the third call into `dispatch()`.
6. Extend `tests/test_meter_slab_recommendation.py` with #19-#29, #22b (dispatch/recipient/dedup/timezone/push-failure/token/flag/no-monetary-claim checks).

**Phase 3 — Read-path integration (depends on Phase 1 only; independent of Phase 2)**
7. `app/schemas/electricity.py` — add `SlabRecommendationResponse`, extend `InsightsResponse`.
8. `app/services/electricity_insights_service.py` — extend `get_insights`.
9. Extend `tests/test_meter_slab_recommendation.py` with #30-#34 (read-path-specific: parity with dispatch, null case, dedup-independence, flag-gating, existing-shape regression).

*(Phases 2 and 3 can run in either order, or concurrently by two people, since neither writes to files the other touches. This plan lists dispatch first only because it's the feature's original MVP scope per `feature-spec.md`; the read path was added by a later consistency pass.)*

**Phase 4 — Frontend (depends on Phase 3's contract being final — it is, per the specs; does not require Phase 3 to be deployed to write against, but does require it to test end-to-end)**
10. `src/services/electricityApi.ts` — add the `SlabRecommendation` interface and extend `InsightsResponse`.
11. `src/index.css` — add the new card classes.
12. `src/pages/Electricity.tsx` — insert the recommendation card JSX.
13. Manual verification (§11 below) — no automated frontend test exists to write.

**Phase 5 — Full-stack verification**
14. Run the full backend suite (`pytest`) — confirm every new test passes and no existing test (`test_electricity.py`, `test_main.py`, etc.) regresses.
15. Manual end-to-end smoke test: seed the feature-spec §2 worked example (meter A at 60 units active, meter B at 0 units standby, slab boundary 100) via direct DB inserts of readings and a billed reading ≥10 days old; confirm `POST /api/v1/push/dispatch?token=...` reports a sent notification; confirm `GET /api/v1/electricity/insights` for the same user returns a matching `slab_recommendation`; confirm the frontend card renders with matching numbers; perform a switch via the existing UI; confirm the card disappears (or updates) on the next page load.

---

## 10. Backend Test Implementation Plan (mapped to Acceptance Criteria)

All in `tests/test_meter_slab_recommendation.py`, per `backend-spec.md` §20 (test list reproduced here with phase/file mapping for traceability; see that section for full descriptions):

| Test # | AC | Phase | Exercises |
|---|---|---|---|
| 1-3 | AC1-AC3 | 1 | `evaluate_switch_recommendation` meter-count eligibility |
| 4 | AC4 | 1 | Active-meter resolution |
| 5 | AC5 | 1 | Missing billing anchor → skip |
| 6-7 | AC6-AC7 | 1 | 10-day evaluation boundary |
| 8-9 | AC8-AC9 | 1 | Configured slabs, no hardcode; buffer math |
| 10-11 | AC10-AC11 | 1 | Rate/projection, recent-vs-overall |
| 12-13 | AC12-AC13 | 1 | Billing-period median/fallback |
| 12b | AC12b | 1 | Duplicate billed dates collapse to distinct dates before interval calculation — no spurious 0-day intervals |
| 12c | — | 1 | Feature-spec §2 worked example still recommends end-to-end once duplicate-dated billing history is deduplicated |
| 14-17 | AC14-AC17 | 1 | Opportunity/standby-meaningfulness decision, both worked examples |
| 18 | AC18 | 1 | Recommended switch date |
| 35 | — | 1 | Settings fields actually read at call time (monkeypatch) |
| 19-21 | AC19-AC21 | 2 | Owner/shared-user push, independent dedup |
| 22, 22b | AC22 | 2 | Daily dedup; next-day re-notification (no cooldown) |
| 23-24 | AC23-AC24 | 2 | Re-evaluation after switch; new billing anchor lifecycle |
| 25 | AC25 | 2 | Non-UTC timezone |
| 26 | AC26 | 2 | Push failure doesn't consume dedup slot |
| 27 | AC27 | 2 | Dispatch token auth unchanged |
| 28 | AC28 | 2 | Feature flag gates dispatch candidate |
| 29 | AC29 | 2 | No currency/guarantee language in push copy |
| 30 | — | 3 | Read-path/dispatch-path parity (no second algorithm) |
| 31 | AC15/17 | 3 | `slab_recommendation: null` when not eligible |
| 32 | — | 3 | Read path ignores `ReminderDispatchLog` |
| 33 | AC28 | 3 | Read path 403s via router-level flag gate |
| 34 | — | 3 | Existing `/insights` fields unaffected |

Plus the edge-case tests `backend-spec.md` §20 lists (zero `SlabThreshold` rows, zero consumption, active meter already in top slab, same-day duplicate reading) — run in Phase 1 alongside tests 1-18, since they exercise the same calculation module.

---

## 11. Frontend Test / Manual Verification Plan (mapped to Frontend Spec)

No automated frontend test runner exists (§1). Manual checklist, run in Phase 4/5 against a local dev server pointed at a backend seeded per §9 step 15:

| Check | Frontend-spec section | Verifies |
|---|---|---|
| Load `/electricity` with a seeded active recommendation → card renders above the meter cards, with correct active/standby labels, units, `limit ~X (slab at Y)` pairs, explanation text, and `Recommended by <date>` | §5, §6, §7, §8, §9 | Card placement/content |
| Same load → no `<Link>`/button rendered inside the card; the pre-existing `Switch Meter` button (below the meter cards) is present exactly once | §10 | No duplicate CTA |
| Tap the existing `Switch Meter` button → lands on `/electricity/switch`, unchanged behavior | §10 | Reused switch flow |
| Load `/electricity` for a user with no valid recommendation → no card, rest of page identical to today | §11 | No-recommendation behavior |
| Throttle/kill network → existing `SkeletonCard`/`.status-error` + Retry cover the whole page, no separate recommendation spinner/error | §13, §14 | Loading/error reuse |
| Perform a switch via the existing flow, return to `/electricity` → card reflects new active/standby pair or disappears if no longer applicable, with no manual refresh needed beyond the existing back-navigation | §15, §16 | Post-switch/staleness behavior |
| Grep the diff for literal `100`/`2` in the touched files | §8 | No hardcoded threshold/buffer |
| Grep the rendered card's text for `$`/currency symbols or "sav" (case-insensitive) | §6, §9 | AC29 — no monetary claim |
| Resize to the narrowest supported mobile width | §17 | Responsive layout |
| Check heading level (`<h3>`), accessible name of the reused button, badge text-not-color-only | §18 | Accessibility |
| Load `Dashboard.tsx` and `ElectricitySwitchMeter.tsx` for a user with a populated `slab_recommendation` → no runtime error from the unconsumed new field | §16 risk (below) | Response-shape backward compatibility |

---

## 12. API Contract Changes

Both additive, no breaking change, no new endpoint (backend-spec §16.1):

**`POST /api/v1/push/dispatch`** response gains one more entry in `sent`/contributes to `processed_users`/`errors`, from the new dispatch operation — shape unchanged.

**`GET /api/v1/electricity/insights`** response gains one new top-level field:

```json
{
  "meters": [ /* unchanged */ ],
  "slab_recommendation": {
    "active_meter_id": "uuid",
    "active_meter_label": "string",
    "standby_meter_id": "uuid",
    "standby_meter_label": "string",
    "active_cumulative_units": 60.0,
    "active_next_slab_min": 100.0,
    "active_operational_threshold": 98.0,
    "standby_cumulative_units": 0.0,
    "standby_next_slab_min": 100.0,
    "standby_operational_threshold": 98.0,
    "recommended_switch_date": "2026-08-26",
    "explanation": "string"
  } // or null
}
```

No auth change on either endpoint. Full field-by-field source mapping: `backend-spec.md` §16.1.

---

## 13. Push-Dispatch Integration

`app/api/push.py`'s `dispatch()` gains a third call, merged into the same response the same way `dispatch_due`/`dispatch_water_due` already are:

```python
skincare_result = PushService.dispatch_due(db)
water_result = PushService.dispatch_water_due(db)
meter_slab_result = PushService.dispatch_meter_slab_recommendation(db)
return {
    "processed_users": skincare_result["processed_users"] + water_result["processed_users"] + meter_slab_result["processed_users"],
    "sent": skincare_result["sent"] + water_result["sent"] + meter_slab_result["sent"],
    "errors": skincare_result["errors"] + water_result["errors"] + meter_slab_result["errors"],
}
```

`dispatch_meter_slab_recommendation(db)` internally: candidate discovery (union of `Meter.user_id`/`MeterShare.shared_with_user_id`) → per-candidate feature-flag check → `evaluate_switch_recommendation` → dedup check against `ReminderDispatchLog` (slot `meter_slab_recommendation_{anchor_reading_id}`) → `PushService.send_to_user` → dedup write only if `sent_count > 0`. Full detail: `backend-spec.md` §4, §12-§14, §18-§19.

---

## 14. `/electricity/insights` Integration

`electricity_insights_service.get_insights(db, user_id)` gains one additional call, placed after its existing `active_meter_id = resolve_active_meter_id(db, user_id)` line (that value is not re-derived — `evaluate_switch_recommendation` re-resolves it internally, which is an accepted minor redundancy per `backend-spec.md` §16.2, not a bug to fix):

```python
recommendation = evaluate_switch_recommendation(db, user_id, local_today())
return {"meters": results, "slab_recommendation": recommendation}
```

`app/api/electricity.py`'s `get_electricity_insights` route needs **no change** — it already just returns whatever `get_insights` returns, and `response_model=InsightsResponse` will serialize the new field automatically once `InsightsResponse` includes it.

---

## 15. Master Acceptance-Criteria Traceability (Feature Spec → Implementation → Test)

Verifies every one of feature-spec.md's 29 acceptance criteria has both an implementation task and a test/verification step, before this plan is considered complete.

| AC | Implementation task | Test / verification |
|---|---|---|
| AC1 | `meter_slab_recommendation_service.py` — 2-meter eligibility check | Backend test #1 |
| AC2 | Same file — 0/1-meter skip | Backend test #2 |
| AC3 | Same file — >2-meter skip | Backend test #3 |
| AC4 | Same file — calls `resolve_active_meter_id` | Backend test #4 |
| AC5 | Same file — billing-anchor hard skip | Backend test #5 |
| AC6 | Same file — `settings.meter_slab_min_evaluation_days` gate | Backend test #6 |
| AC7 | Same file — evaluation begins at the boundary | Backend test #7 |
| AC8 | Same file — `bracket_for`/`_next_slab_min` reuse; `schemas/electricity.py` exposes the resulting values | Backend tests #8, #30 |
| AC9 | Same file — `settings.meter_slab_safety_buffer_units` | Backend test #9 |
| AC10 | Same file — overall-rate projection | Backend test #10 |
| AC11 | Same file — `max(overall, recent)` | Backend test #11 |
| AC12 | Same file — median of historical intervals | Backend test #12 |
| AC12b | Same file — intervals computed from distinct billed `reading_date` values, not raw rows (duplicate-billing-dates fix) | Backend tests #12b, #12c |
| AC13 | Same file — `settings.meter_slab_default_billing_period_days` fallback | Backend test #13 |
| AC14 | Same file — `opportunity_exists` check | Backend test #14 |
| AC15 | Same file — `standby_is_meaningful` false case | Backend tests #15, #31 |
| AC16 | Same file — `standby_is_meaningful` true case | Backend test #16 |
| AC17 | Same file — the literal A=98/B=99 worked example | Backend test #17 |
| AC18 | Same file — `recommended_switch_date` | Backend test #18 |
| AC19 | `push_service.py` — owner in candidate pool | Backend test #19 |
| AC20 | Same file — shared user in candidate pool | Backend test #20 |
| AC21 | Same file — independent per-recipient dedup | Backend test #21 |
| AC22 | Same file — `ReminderDispatchLog` daily uniqueness | Backend test #22 |
| AC23 | Same file + `electricity_insights_service.py` — fresh evaluation every call, no cached state | Backend test #23 |
| AC24 | `push_service.py` — anchor-embedded slot naming | Backend test #24 |
| AC25 | `meter_slab_recommendation_service.py`/`push_service.py` — `local_today()` throughout | Backend test #25 |
| AC26 | `push_service.py` — dedup write only after `sent_count > 0` | Backend test #26 |
| AC27 | `app/api/push.py` — token check untouched | Backend test #27 |
| AC28 | `push_service.py` (manual query) + `app/api/electricity.py` (existing router dependency) | Backend tests #28, #33 |
| AC29 | `push_service.py` (`METER_SLAB_MESSAGE`) + `meter_slab_recommendation_service.py` (`explanation` generator) + `Electricity.tsx` (renders verbatim, no client-side composition) | Backend test #29 + frontend manual currency/guarantee-language check (§11) |

All 29 covered, plus AC12b (added in this revision to fix a real duplicate-billing-dates suppression bug found during local verification — see backend-spec.md §6/§19/Revision note 4). No acceptance criterion is implemented without a corresponding test or verification step, and none is tested without a corresponding implementation task.

---

## 16. Risks / Areas Where Implementation Could Accidentally Violate the Specs

Ordered roughly by how easy the mistake would be to make, not by severity — all are worth a deliberate check during code review, since none of them would necessarily fail obviously at runtime.

1. **Reimplementing the algorithm instead of calling `evaluate_switch_recommendation`.** The single biggest risk: someone under time pressure inlines rate/threshold math directly into `push_service.py` or `electricity_insights_service.py` "just for this one case." **Guard**: code review checklist — `bracket_for`, `_next_slab_min`, and `compute_cumulative` should appear in exactly one new file (`meter_slab_recommendation_service.py`) plus their existing call site in `electricity_insights_service.get_insights`'s own per-meter loop; they should **not** appear again in `push_service.py` or a second time in `electricity_insights_service.py`.

2. **Read path accidentally consulting `ReminderDispatchLog`.** E.g. adding "don't show the card if already notified today" logic to `get_insights`, which directly contradicts backend-spec §14/§16.3. **Guard**: test #32 is written specifically to catch this; also grep `electricity_insights_service.py` for `ReminderDispatchLog` after the change — it should not appear.

3. **Hardcoding one of the four parameters.** Writing `next_min - 2` or `elapsed_days >= 10` instead of the `settings.meter_slab_*` reference. **Guard**: test #35 (settings monkeypatch) fails if any value is hardcoded instead of read live; also grep the new service file for bare `2`, `10`, `30` literals outside of the `Settings` field defaults themselves.

4. **Frontend recomputing or duplicating.** E.g. the card computing `active_next_slab_min - 2` itself, or adding its own "is this urgent" logic instead of trusting `slab_recommendation` verbatim. **Guard**: diff review — no arithmetic should appear on any `slab_recommendation.*` field in `Electricity.tsx`; literal `100`/`2` must not appear in the diff (frontend-spec §8).

5. **Reintroducing a duplicate `Switch Meter` button in the card.** Directly contradicts frontend-spec §10's explicit, revised decision. **Guard**: manual check in §11's checklist — exactly one such button/link on the page when a recommendation is active.

6. **Dispatch and read-path callers diverging on `today`.** If one caller uses `local_today()` and the other uses `datetime.utcnow().date()` (the pattern `get_insights`'s *existing* `days_since_bill` field already uses, per backend-spec §15), the two callers could disagree near a UTC/local-timezone day boundary, breaking test #30's parity guarantee. **Guard**: both `push_service.py`'s new method and `electricity_insights_service.get_insights`'s new call must use `app.core.timezone.local_today()` — not the older inline `ZoneInfo` pattern, not naive `utcnow()`.

7. **Accidentally triggering a migration.** If `SwitchRecommendation` (or any part of the new module) is ever added to `app/models/` or otherwise registered on `Base.metadata` — even unintentionally, e.g. by importing it from a file that also imports models — an `alembic revision --autogenerate` run could pick up a phantom change. **Guard**: `meter_slab_recommendation_service.py` should have no import of `app.database.base.Base` and no SQLAlchemy `Mapped`/`mapped_column` usage; it deals only in plain Python values and existing models' *rows*, never new schema.

8. **`/insights`'s other existing consumers breaking on the new field.** `Dashboard.tsx`'s electricity tile and `ElectricitySwitchMeter.tsx` both call `getInsights()` too; TypeScript's structural typing makes an *additive* field safe by construction, but it's worth an explicit manual check (§11's last row) rather than assuming — especially since none of those call sites destructure `slab_recommendation`, so a typo in the interface wouldn't be caught by them at all.

9. **Push copy and `explanation` bleeding into each other.** Copy-pasting the fixed push body into the `explanation` generator (making the card generic and losing the specific numbers/date frontend-spec §9 requires), or conversely templating the push body per-user (violating feature-spec §21's "no interpolation" rule for the notification itself). **Guard**: `METER_SLAB_MESSAGE` must remain a literal constant tuple with zero `.format()`/f-string usage; the `explanation` generator is a separate function that never reads or writes `METER_SLAB_MESSAGE`.

10. **Off-by-one on the 10-day boundary or the `>`/`>=` comparisons in the decision logic.** feature-spec AC6/AC7 require `elapsed_days >= 10` (not `>`); backend-spec §10 requires a strict `>` for `remaining_capacity_standby > remaining_capacity_active` (not `>=`, to avoid recommending a switch to an equally-good meter). **Guard**: tests #6/#7 and #17 target exactly these boundaries — do not consider Phase 1 done until both pass.

11. **A stray `db.commit()`/`db.rollback()` inside the calculation module.** `meter_slab_recommendation_service.py` runs inside whatever `db` session its caller already has open (a request-scoped session for the read path, a batch session for dispatch); it must stay read-only. **Guard**: grep the new file for `.commit()`/`.rollback()` — neither should appear.

12. **One user's bad data aborting the whole dispatch batch.** `dispatch_due`/`dispatch_water_due` already have no per-candidate `try/except` (a pre-existing gap, `backend-spec.md` §19); the new function sits in the same request as those two and runs after them — an uncaught exception in it would also prevent... actually, since it's added *after* the other two calls in `push.py`'s `dispatch()`, a crash in the new function can't block the other two (they've already run), but it would still 500 the whole HTTP response and lose its own `result` for that run. **Guard**: implement the per-candidate `try/except Exception` backend-spec §19 recommends for this new function specifically, so one bad candidate's electricity data can't take down the entire run's own reporting, even though it wouldn't affect the other two features' dispatch.

13. **Regressing the distinct-billing-dates deduplication (AC12b).** Billed `MeterReading` rows sharing a calendar date must collapse to one date before interval calculation — a future edit to §6's logic (e.g. "simplifying" it back to a plain pairwise-diff over the raw row list) would silently reintroduce the exact suppression bug this revision fixes, without failing loudly (no exception, just a `slab_recommendation` that quietly goes missing for any user with a duplicate-dated shared-meter billing history). **Guard**: test #12b asserts the specific `[Jul 06 ×3, Aug 09 ×2] → 34-day interval, not [0,0,34,0]` regression case; do not remove or weaken it, and do not reintroduce a raw (non-deduplicated) date list anywhere in the interval calculation.
