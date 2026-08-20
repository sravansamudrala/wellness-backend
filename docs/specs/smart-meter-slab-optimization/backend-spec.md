# Smart Meter Slab Optimization — Backend Spec

Status: draft, implementation-ready — no open implementation questions remain (§24).

**Revision note:** billing-period estimation scope (both meters), the minimum-intervals threshold (2), the removal of a separate calendar-day switch buffer, and the re-notification/dedup policy (daily-only, no cooldown) are now confirmed product decisions and are reflected throughout this revision — they are no longer listed as open questions. See §23 for the consolidated list of what changed.

**Revision note 2 (frontend contract):** `frontend-spec.md`'s consistency pass identified that the frontend's recommendation card cannot be built from the push notification alone (a notification can't be "re-read" later). §16 is rewritten accordingly: `GET /api/v1/electricity/insights` now returns a `slab_recommendation` field, computed by the exact same evaluation logic already specified in §5-§11 — no second algorithm, no new endpoint, no change to any confirmed business rule, and `ReminderDispatchLog` plays no part in what this field returns. This resolves what was previously Open Implementation Question §24 item 1; that question is removed. See §23.2 for the full statement of this decision and its consequences across §1, §2, §4, §12-§14, §18-§21.

**Revision note 3 (configurable parameters):** the four feature parameters (`MIN_EVALUATION_DAYS`, `SLAB_SAFETY_BUFFER_UNITS`, `DEFAULT_BILLING_PERIOD_DAYS`, `MIN_BILLING_INTERVALS_FOR_ESTIMATE`) are no longer module-level constants — confirmed, they are added to `app/core/config.py`'s `Settings` class as env-var-configurable fields, following the `reminder_timezone`/`dispatch_token` precedent rather than the `MAX_METERS_PER_USER`/`APPROACHING_FRACTION` precedent the previous revision chose. §22 is rewritten accordingly, and every code-block reference to the old ALL_CAPS names throughout §6-§10 and §16 is updated to the corresponding `settings.*` field. This resolves the last Open Implementation Question; §24 is now empty.

**Revision note 4 (duplicate billing dates):** local verification against real data surfaced a correctness bug in §6's billing-period estimation: it computed intervals from the *raw* list of billed `MeterReading` rows, so multiple rows sharing one calendar date (e.g. a shared meter billed once but confirmed by more than one accessible user) produced spurious 0-day intervals, pulling the median toward `0` and collapsing `expected_billing_period_end` to the billing anchor date itself — permanently suppressing the recommendation regardless of the actual consumption picture. §4 query 9, §6, §19, §20, and §21 are updated: intervals are now computed from the **distinct** set of billed `reading_date` values, not the raw row list. New acceptance criterion AC12b (feature-spec §28) and backend tests #12b/#12c cover this. No other confirmed decision in §23 changes — the minimum-2-intervals rule, the 30-day fallback, both-meters scope, the 10-day gate, the safety buffer, full handoff, and dedup/notification behavior are all unchanged.

Source of truth: [`feature-spec.md`](./feature-spec.md). This document does not reopen any decision made there — it translates it into concrete backend contracts for the existing FastAPI / SQLAlchemy / PostgreSQL codebase at `wellness-backend`. Section numbers below are independent of the feature spec's numbering.

This spec **does not** modify application code and **does not** define any migration. Everything in §4 is a statement that no schema change is required; where a new module/function is described, it is a plan for a future implementation PR, not code delivered by this document.

---

## 1. Backend Architecture and Components

New code, all additive:

| Component | File | Responsibility |
|---|---|---|
| Pure calculation module | `app/services/meter_slab_recommendation_service.py` (new) | Billing-period estimation, consumption-rate/projection math, slab/buffer math, switch-decision logic, recommended-switch-date math, explanation-text generation, per-user eligibility evaluation. No DB writes, no push calls, no `ReminderDispatchLog` reads. |
| Shared evaluation entrypoint | `evaluate_switch_recommendation(db, user_id, today) -> SwitchRecommendation \| None`, in the module above | **The single function both call sites below use — see the callout right after this table.** Runs the full §5-§11 pipeline for one user and returns either a populated result or `None`; never partially applies the logic. |
| Dispatch orchestration | `app/services/push_service.py` — new `PushService.dispatch_meter_slab_recommendation(db)` static method (existing file, additive method only) | Candidate-user discovery, feature-flag gate, calls `evaluate_switch_recommendation` per candidate, dedup check/write against `ReminderDispatchLog`, calls `PushService.send_to_user`. Mirrors the existing `dispatch_due` / `dispatch_water_due` shape. |
| Dispatch wiring | `app/api/push.py` — `dispatch()` route (existing file, additive call only) | Add a third call alongside `dispatch_due`/`dispatch_water_due`, merge results into the same response shape. |
| Read-path integration | `app/services/electricity_insights_service.py` — `get_insights(db, user_id)` (existing function, additive change) + `app/schemas/electricity.py` — new `SlabRecommendationResponse` schema | Calls `evaluate_switch_recommendation` once for the requesting user and includes the result (or `null`) as a new `slab_recommendation` field in the existing `/insights` response. No dedup, no push side effects, no new endpoint (§16). |
| Config | `app/core/config.py` — `Settings` class (existing file, additive fields only) | Four new env-var-configurable fields: `meter_slab_min_evaluation_days`, `meter_slab_safety_buffer_units`, `meter_slab_default_billing_period_days`, `meter_slab_min_billing_intervals_for_estimate` (see §22). `meter_slab_safety_buffer_units` is the **only** safety margin used anywhere in this feature — there is no separate calendar-day switch buffer in V1 (see §11). |

This mirrors the existing split in the electricity module itself: `electricity_service.py` (writes) vs. `electricity_insights_service.py` (pure read/compute logic) — the new calculation module plays the same role `electricity_insights_service.py` plays for the insights endpoint, and `PushService.dispatch_*` plays the same role it already plays for skincare/water. No new abstraction is introduced beyond what those two precedents already establish.

**Why one shared function, not two callers each doing their own thing:** `dispatch_meter_slab_recommendation` and `get_insights` need the identical decision (does a recommendation exist right now for this user, and if so, what are its numbers) for two different purposes — one to decide whether to push, one to decide what to render. Giving each its own copy of §5-§11's logic would be exactly the "second recommendation algorithm" this feature must not create; instead, both call `evaluate_switch_recommendation(db, user_id, today)` and do nothing with its output except what's specific to their own job (dispatch: dedup + send; read path: serialize to JSON). Neither caller re-derives, re-checks, or overrides any part of the decision.

No new API router, no new pip dependency. **One new Pydantic response model** (`SlabRecommendationResponse`, §16) is added to `app/schemas/electricity.py`, nested optionally inside the existing `InsightsResponse` — this is the one place the "no new Pydantic schemas" statement from earlier drafts of this spec no longer holds, superseded by §16.

---

## 2. Existing Code / Helpers Reused (do not reimplement)

| Symbol | File:line | Reused as-is for |
|---|---|---|
| `accessible_meter_ids(db, user_id)` | `app/services/electricity_insights_service.py:23` | Per-candidate-user meter-count/eligibility check (§10 in feature-spec, AC1–AC3) |
| `resolve_active_meter_id(db, user_id)` | `app/services/electricity_insights_service.py:49` | Active/standby resolution (AC4) |
| `compute_cumulative(db, meter)` | `app/services/electricity_insights_service.py:110` | Current-period consumption for both meters (§9 feature-spec, AC-adjacent) |
| `bracket_for(cumulative, slabs)` | `app/services/electricity_insights_service.py:121` | Current slab bracket, for both meters (AC8) |
| `_next_slab_min(bracket, slabs)` | `app/services/electricity_insights_service.py:132` | Next slab boundary, for both meters (AC8, AC9) |
| `Meter`, `MeterReading`, `MeterSwitchEvent`, `MeterShare`, `SlabThreshold` | `app/models/electricity.py` | All reads; zero model changes |
| `PushService.send_to_user(db, user_id, title, body)` | `app/services/push_service.py:57` | Delivery (AC19, AC20, AC26) |
| `ReminderDispatchLog` + its `(user_id, sent_on, slot)` unique constraint | `app/models/reminder_dispatch_log.py` | Deduplication (AC22) |
| `dispatch_due` / `dispatch_water_due` control-flow shape | `app/services/push_service.py:106`, `:179` | Template for `dispatch_meter_slab_recommendation`'s loop/dedup/send/log sequencing (see §5, §15) |
| `POST /api/v1/push/dispatch` + `settings.dispatch_token` check | `app/api/push.py:34` | Auth + wiring point (AC27) |
| `FeatureFlag` model | `app/models/feature_flag.py` | Direct query (not `require_feature`, which is HTTP-shaped) to gate the dispatch path (AC28) |
| `app/core/timezone.py` (`local_now`, `local_today`) | — | Timezone-aware "today" for the new code (AC25) — see §15 for why this is preferred over `push_service.py`'s inline `ZoneInfo` pattern for *this* feature specifically |

`bracket_for`/`_next_slab_min` are pure functions that take an already-fetched `List[SlabThreshold]` — the new code queries `SlabThreshold` per meter itself (one query per meter, or one batched query for both, same pattern `get_insights` already uses at `electricity_insights_service.py:182-188`).

`_anchor_and_latest_reading` (the private helper behind `compute_cumulative`, same file, line 81) is **not** imported directly — it's private (`_`-prefixed) — but its logic is exactly what's needed for the recent-rate calculation (§8) and billing-anchor resolution (§4 in feature-spec). Rather than reaching into a private helper, the new module queries `MeterReading` itself using the identical ordering (`reading_date desc, created_at desc` / `asc, asc`) so behavior stays consistent without depending on another module's private API.

---

## 3. Required Database Changes

**None.** No migration, no new table, no new column, no new index.

Every piece of state this feature needs already exists:

- Billing anchor → `Meter.last_billed_reading_id`
- Consumption history → `MeterReading`
- Slab config → `SlabThreshold`
- Active/standby → derived from `MeterSwitchEvent` via `resolve_active_meter_id`
- Sharing → `MeterShare`
- Feature gating → `FeatureFlag`
- Dedup → `ReminderDispatchLog`, using a new **value convention** in the existing `slot` column (a plain unindexed-beyond-the-existing-constraint `String`, so no length migration is needed either) — see §15.

V1 deliberately has no escalation/cooldown state to persist (§14, §23.2 — confirmed daily-only dedup) — if a future revision ever wanted to distinguish "still valid" from "materially more urgent," that would need a new column to persist last-notified state, but that is not part of this feature.

---

## 4. Required Queries

Queries 1, 2, 10, and 11 are **dispatch-orchestration-specific** — they only ever run inside `PushService.dispatch_meter_slab_recommendation`, because they concern *finding which users to evaluate* and *deduping/sending a push*, neither of which applies to the read path (§16 covers a single already-authenticated user, and never touches `ReminderDispatchLog`). Queries 3-9 are the **shared evaluation** queries — they run inside `evaluate_switch_recommendation(db, user_id, today)` (§1), called once per candidate by the dispatch path and once per request by `get_insights` (§16); nothing about them changes based on which caller invoked the function.

1. **Candidate discovery** (dispatch-only; new — no existing analogue since there's no `ElectricityReminderSettings` table):
   ```sql
   SELECT DISTINCT user_id FROM meters
   UNION
   SELECT DISTINCT shared_with_user_id FROM meter_shares
   ```
   via two `db.query(...).distinct()` calls unioned in Python (consistent with `accessible_meter_ids`'s own style of two plain queries rather than a SQL `UNION`). This is the candidate pool — every user who owns or has shared access to at least one meter. Feature-flag and 2-meter eligibility are then applied per candidate (§9).

2. **Feature flag check** (dispatch-only) — direct query, not `require_feature` (which raises `HTTPException` and is HTTP-request-shaped). The read path needs no equivalent query of its own: `GET /api/v1/electricity/insights` is already behind `Depends(require_feature("electricity_tracker"))` at the router level (`electricity.py:25`, unchanged), so by the time `get_insights`/`evaluate_switch_recommendation` runs, the flag check has already happened (§18):
   ```python
   db.query(FeatureFlag).filter(
       FeatureFlag.user_id == user_id,
       FeatureFlag.feature_key == "electricity_tracker",
       FeatureFlag.enabled.is_(True),
   ).first()
   ```

3. **Accessible meters** — `accessible_meter_ids(db, user_id)`, reused verbatim.

4. **Active meter** — `resolve_active_meter_id(db, user_id)`, reused verbatim.

5. **Billing anchor** — `Meter.last_billed_reading_id` on the active `Meter` row, resolved to a `MeterReading` by primary key.

6. **Current-period consumption**, both meters — `compute_cumulative(db, meter)`, reused verbatim, called once per meter (active and standby).

7. **Slab thresholds**, both meters:
   ```python
   db.query(SlabThreshold).filter(SlabThreshold.meter_id.in_([active_id, standby_id])).all()
   ```
   grouped by `meter_id` in Python, same pattern as `get_insights`.

8. **Recent-reading-interval** (for recent-rate, §8), active meter only:
   ```python
   db.query(MeterReading).filter(MeterReading.meter_id == active_meter.id)
     .order_by(MeterReading.reading_date.desc(), MeterReading.created_at.desc())
     .limit(2).all()
   ```

9. **Historical billed readings** (for billing-period estimation, §6), across **both** accessible meters (scope confirmed in §6/§23.2 — no longer an open question):
   ```python
   db.query(MeterReading).filter(
       MeterReading.meter_id.in_([active_id, standby_id]),
       MeterReading.is_billed_reading.is_(True),
   ).order_by(MeterReading.reading_date.asc()).all()
   ```
   This raw query can return multiple rows sharing the same `reading_date` — most commonly a shared meter where more than one accessible user logs/confirms a reading for the same real-world bill. §6 reduces these rows to their **distinct** `reading_date` values before computing intervals; the query itself is intentionally not `DISTINCT`-qualified, so the deduplication is an explicit step in the calculation module, not an implicit property of the query.

10. **Dedup check** (dispatch-only) — `ReminderDispatchLog` filtered by `(user_id, slot)` (not scoped to `sent_on == today` alone — see §15 for why the query is broader than the existing `dispatch_due` pattern).

11. **Dedup write** (dispatch-only) — `db.add(ReminderDispatchLog(user_id=user_id, sent_on=today, slot=slot))`, only after `PushService.send_to_user` reports `sent_count > 0` — identical convention to `dispatch_due`/`dispatch_water_due` (AC26).

**The read path (§16) never queries `ReminderDispatchLog` at all** — not queries 10, 11, or any other. Whether a push was already sent today, or on any other day, has no bearing on what `slab_recommendation` returns; it reflects only `evaluate_switch_recommendation`'s current-state evaluation (queries 3-9).

No N+1 concern beyond what `dispatch_due`/`dispatch_water_due` already accept (no pagination/batching exists there either) — same acceptable scale assumption, not something this spec changes.

---

## 5. Consumption Calculation

Reused exactly: `compute_cumulative(db, meter)` for **both** the active and the standby meter. No second definition is introduced anywhere in the new module, satisfying Implementation Principle #3.

One nuance the new code must respect: `compute_cumulative`'s anchor fallback (first-ever reading when `last_billed_reading_id is None`) is correct for the **standby** meter (its own display/insights purposes are unaffected either way — the standby's cumulative is only used relative to its own slabs, not gated by whether it's "billed"), but per feature-spec §7, a **missing anchor on the active meter is a hard skip for the whole recommendation** — never treated as "cumulative since first reading." The new code therefore checks `Meter.last_billed_reading_id is not None` on the *active* meter explicitly, before calling `compute_cumulative` for evaluation purposes (calling it after that check, so the value returned is guaranteed to be relative to a real bill).

---

## 6. Billing-Period Estimation

```
historical billed readings (both accessible meters, is_billed_reading=True)
  -> distinct_dates = sorted(set of each row's reading_date)   # duplicate billing dates collapse to one — see below
  -> pairwise consecutive date diffs of distinct_dates = "historical intervals" (in days)
  -> if count(intervals) >= settings.meter_slab_min_billing_intervals_for_estimate:      # default 2, confirmed
         typical_billing_period_days = round(median(intervals))
     else:
         typical_billing_period_days = settings.meter_slab_default_billing_period_days  # fallback, flagged as an estimate
expected_billing_period_end = anchor.reading_date + timedelta(days=typical_billing_period_days)
```

- Uses `statistics.median` semantics (not mean), per feature-spec §14.
- **Confirmed: scope is both accessible meters combined**, not the active meter alone. Historical billed readings are pooled across the user's two meters, sorted chronologically, and consecutive diffs taken across that combined timeline — because a freshly-switched-to active meter frequently has zero or one billed reading of its own, which would make active-meter-only estimation fall back to the default far more often than necessary.
- **Confirmed: `settings.meter_slab_min_billing_intervals_for_estimate` defaults to `2`** (i.e., at least 3 distinct pooled billing dates before trusting the median over the 30-day fallback), and is now an env-var-configurable `Settings` field rather than a module constant — see §22.
- **Confirmed: intervals are computed from the distinct set of billed `reading_date` values, not the raw row list** (feature-spec §14, "Duplicate billing dates" / §27's matching edge case). Multiple billed `MeterReading` rows can legitimately share one calendar date — most commonly a shared meter where more than one accessible user logs or confirms a reading for the same real-world bill. Without deduplication, `n` rows sharing a date contribute `n-1` spurious 0-day intervals, pulling the median toward `0` and collapsing `expected_billing_period_end` to the anchor date itself — permanently suppressing the recommendation regardless of the actual consumption picture. This was observed against real data, not hypothesized: raw billed dates `Jul 06, Jul 06, Jul 06, Aug 09, Aug 09` previously produced intervals `[0, 0, 34, 0]` (median `0`); with distinct-date deduplication they reduce to `Jul 06, Aug 09`, a single `34`-day interval, and the estimate is never `0` for this input (AC12b).
- `round()` on an even-count median (average of two ints) uses Python's default (banker's) rounding — acceptable here since the feature spec treats this whole figure as an estimate, not an exact value (§14: "must be treated as an estimate, not as the customer's confirmed billing cycle").

---

## 7. Consumption-Rate / Projection Algorithm

```
elapsed_days = (today_local - anchor.reading_date).days
overall_rate = cumulative_active_units / elapsed_days        # elapsed_days > 0 guaranteed by the settings.meter_slab_min_evaluation_days gate

last_two = latest 2 readings for the active meter, by (reading_date desc, created_at desc)
if len(last_two) == 2 and last_two[0].reading_date != last_two[1].reading_date:
    recent_rate = (last_two[0].reading_value - last_two[1].reading_value) / (last_two[0].reading_date - last_two[1].reading_date).days
else:
    recent_rate = None   # can't compute reliably (fewer than 2 readings, or same-day duplicate)

projection_rate = max(overall_rate, recent_rate) if recent_rate is not None else overall_rate

if cumulative_active_units <= 0 or projection_rate <= 0:
    -> skip: no projection-based recommendation (feature-spec §12, §27 "Zero consumption")
```

Why `last_two` (the meter's two most-recent readings overall, not explicitly re-filtered to "after the anchor"): `ElectricityService._build_reading` (`electricity_service.py:199-204`) enforces that `reading_date` is monotonically non-decreasing within a meter's reading log. Since the anchor is itself a reading in that same monotonic log, the reading immediately preceding "latest" is always at or after the anchor's date — the recent interval can never accidentally straddle a previous billing period into this one. This is derived from an existing invariant, not a new assumption.

`overall_rate`'s denominator is calendar days to **today**, not to the latest reading's date — this is intentional per feature-spec §12 (it's what makes `overall_rate` degrade conservatively if the user hasn't logged a reading in a while, which `max(overall, recent)` then corrects for using whichever is more urgent).

Projected operational-threshold date (active meter):
```
operational_threshold_active = next_slab_min(bracket_for(cumulative_active, active_slabs)) - settings.meter_slab_safety_buffer_units
remaining_capacity_active = operational_threshold_active - cumulative_active_units

if next_slab_min(...) is None:
    -> skip: active meter is in its open-ended top slab, no further boundary to project toward
       (feature-spec §27, "Active meter already beyond the next slab" — switching can't undo
       slab consumption already recorded, and there's nothing further to optimize toward)

projected_days_to_threshold = remaining_capacity_active / projection_rate     # may be <= 0 if already past
projected_operational_threshold_date = today_local + timedelta(days=floor(projected_days_to_threshold))
```

`floor()` (not `ceil()` or round-to-nearest) is used when converting the fractional day count to a calendar date, biasing the projected date **earlier** rather than later — consistent with the safety-buffer philosophy that runs through the whole feature (§11 of feature-spec: plan around reaching the threshold sooner rather than later). This is a minor, low-stakes rounding convention, not a product decision requiring sign-off.

---

## 8. Slab and Safety-Buffer Calculation

Reused exactly, per meter (both active and standby, each using **its own** `SlabThreshold` rows — feature-spec §10 and the "Different slab configurations" edge case explicitly require this rather than assuming identical thresholds):

```
bracket = bracket_for(cumulative, meter_slabs)
next_min = _next_slab_min(bracket, meter_slabs)
operational_threshold = next_min - settings.meter_slab_safety_buffer_units if next_min is not None else None
```

`settings.meter_slab_safety_buffer_units` defaults to `2` per feature-spec §11, added as an env-var-configurable field on `app/core/config.py`'s `Settings` class — same pattern as `reminder_timezone`/`dispatch_token`, not a module-level constant. See §22 for the full rationale.

---

## 9. Active vs Standby Meter Evaluation

Both meters are evaluated with the identical calculation (§7's threshold/remaining-capacity math, minus the active-only rate projection), each against its **own** slabs and its **own** `compute_cumulative` result:

| | Active meter | Standby meter |
|---|---|---|
| Cumulative | `compute_cumulative(db, active_meter)` | `compute_cumulative(db, standby_meter)` |
| Slabs | `active_meter`'s own `SlabThreshold` rows | `standby_meter`'s own `SlabThreshold` rows |
| Bracket / next boundary | `bracket_for` / `_next_slab_min` | `bracket_for` / `_next_slab_min` |
| Operational threshold | `next_min - settings.meter_slab_safety_buffer_units` | `next_min - settings.meter_slab_safety_buffer_units` |
| Remaining safe capacity | `operational_threshold - cumulative` | `operational_threshold - cumulative` |
| Rate-based projection | Yes (§7 — drives the primary evaluation) | Only as a *derived* figure using the **active meter's** `projection_rate` (see §10 — this is the "full-handoff" assumption: after a switch, future consumption accrues on the standby meter at roughly the same household usage velocity, not at some independently-observed standby rate, since a standby meter's own reading history is often sparse or stale) |

The standby meter's *own* independent rate is deliberately not used for the primary decision — a meter that isn't currently active is frequently under-logged, so its own historical rate is not a reliable signal. This is the concrete backend interpretation of "full-handoff model": one continuous consumption stream, currently on the active meter, hypothetically moved entirely onto the standby meter — never a split/blended stream across both.

---

## 10. Switch Recommendation Decision Logic

```
opportunity_exists =
    projected_operational_threshold_date is not None
    and projected_operational_threshold_date < expected_billing_period_end        # feature-spec §15, AC14

if not opportunity_exists:
    -> no recommendation, done (nothing further to evaluate)

remaining_capacity_standby = operational_threshold_standby - cumulative_standby   # may be negative

standby_is_meaningful =
    operational_threshold_standby is not None
    and remaining_capacity_standby > remaining_capacity_active

recommend_switch = opportunity_exists and standby_is_meaningful
```

**Confirmed: no additional arbitrary standby-headroom constant.** There is deliberately no `MIN_STANDBY_HEADROOM_UNITS`-style floor — a strictly-greater remaining safe capacity on the standby meter is by itself what counts as "meaningful." `settings.meter_slab_safety_buffer_units` (already baked into both `operational_threshold` values) is the only margin in the calculation; layering a second, separate "meaningfulness" margin on top would be exactly the kind of extra tunable this revision was asked to avoid.

Worked check against feature-spec's own worked examples:

- **§2 example 1** (A=60 active, B=0 standby, next slab 100, buffer 2): `operational_threshold = 98` both. `remaining_capacity_active = 38`. `remaining_capacity_standby = 98`. `98 > 38` → recommend. Matches the feature spec's narrative expectation.
- **§16 / AC17** (A=98 active, B=99 standby, 5 days remaining, same slabs): `remaining_capacity_active = 0`. `remaining_capacity_standby = 98 - 99 = -1` (B is already *past* its own operational threshold). `-1 > 0` is false → no recommendation. Correctly matches AC17's required behavior ("must not blindly recommend switching from A to B").

This single strict comparison (`remaining_capacity_standby > remaining_capacity_active`) is what implements feature-spec §17's three priorities (keep consumption below threshold; avoid pushing a second meter into a higher slab; pick the meter with more safe headroom) as one arithmetic rule rather than three separate checks — they reduce to the same comparison once "safe headroom" is defined consistently for both meters. Using a strict `>` (not `>=`) already prevents recommending a switch to a meter with identical or worse headroom, without needing a separate minimum-margin constant.

---

## 11. Recommended Switch-Date Calculation

**Confirmed: there is no separate calendar-day switch-safety buffer in V1.** The recommended switch date is simply the projected date on which the active meter reaches its safety-adjusted operational threshold — the unit-based `settings.meter_slab_safety_buffer_units` (already folded into `operational_threshold_active`, §8) is the sole safety margin anywhere in this feature. No second, day-based margin is stacked on top of it.

```
recommended_switch_date = projected_operational_threshold_date
```

(`projected_operational_threshold_date` as computed in §7: `today_local + timedelta(days=floor(remaining_capacity_active / projection_rate))`.)

This means "recommend switching now" and "the meter is projected to cross its safety-adjusted threshold on this date" are the same statement — there is no earlier "give yourself N extra days" date computed separately. If `projected_operational_threshold_date` is today or in the past (the projection is already imminent or overdue), the recommended switch date is simply that same date — not an error, and not adjusted further; the notification copy (§13) doesn't literally say "switch by [date]," so there's no display inconsistency — the computed date is available to callers/analytics but isn't required to be in the push payload itself, since §21 of feature-spec fixes the notification copy verbatim with no date interpolation.

---

## 12. Recipient Resolution for Owners and MeterShare Users

**Design: recipients are not "fanned out" from one computed meter pair — they fall out naturally from evaluating every candidate user independently**, per feature-spec §4 ("Evaluate each user independently") and §20 ("Recipients must be evaluated independently").

Concretely: the candidate pool from §4 query 1 (every `Meter.user_id` and every `MeterShare.shared_with_user_id`) is iterated exactly once, and **each candidate runs the full pipeline using their own `accessible_meter_ids`/`resolve_active_meter_id`** — not a shared computation reused across recipients. This means:

- The meter **owner** is naturally in the candidate pool (via `Meter.user_id`) and evaluates using their own accessible set (their two meters).
- A **shared user** is naturally in the candidate pool (via `MeterShare.shared_with_user_id`) and evaluates using *their* accessible set.
- If a shared user has been granted `MeterShare` access to **both** of the pair's meters, their `accessible_meter_ids`/`resolve_active_meter_id` results are identical to the owner's, so they receive the identical recommendation, independently deduplicated (AC21).
- If a shared user has access to only **one** of the two meters, their own `accessible_meter_ids` returns a single meter — they fail the "exactly two accessible meters" eligibility gate (feature-spec §4, "Users with zero or one accessible meter are skipped") and are **not** notified, even though the owner might be. This is the concrete backend meaning of AC20's "...and is an eligible recipient" qualifier — eligibility is evaluated per recipient, not inherited from the owner's eligibility.

This reuses `accessible_meter_ids`/`resolve_active_meter_id` exactly as they already exist and requires **no new fan-out/recipient-resolution helper** — consistent with Implementation Principle #7's explicit instruction not to build one unless implementation reveals a clear need. "The owner of the relevant meter" and "users with MeterShare access to the active meter" (feature-spec §20) are the same meter (the active one) in every case that reaches the notification step, since a candidate's own `resolve_active_meter_id` is definitionally the meter their notification is about.

**This section describes the dispatch path only.** The read path (§16) has no recipient-resolution concept at all — `GET /api/v1/electricity/insights` already answers "for this one authenticated `user_id`" (from the JWT, via `get_current_user`), exactly as it does for every other field in that response. It calls `evaluate_switch_recommendation(db, user_id, today)` for that single user and returns whatever comes back; there is no fan-out, no iteration over owners/shared-users, and no push involved. An owner and a shared user each viewing `/insights` themselves each get their own `slab_recommendation` computed independently, same as they'd each independently be a dispatch candidate — but the read path doesn't loop over anyone, since HTTP already scopes the request to one caller.

---

## 13. Push Notification Behavior

- Delivery: `PushService.send_to_user(db, user_id, title, body)`, called once per eligible recipient — reused verbatim, no changes to that method.
- Copy (fixed, feature-spec §21, no interpolation):
  - Title: `⚡ Consider switching meters`
  - Body: `Your usage is approaching the next slab. Switching your active meter may help keep one meter within the lower usage slab.`
  - Defined as a module-level constant tuple in the new service (or in `push_service.py` alongside `SLOT_MESSAGES`/`WATER_MESSAGE`, matching that file's existing convention at lines 22-27) — e.g. `METER_SLAB_MESSAGE = ("⚡ Consider switching meters", "Your usage is approaching the next slab. Switching your active meter may help keep one meter within the lower usage slab.")`.
- No monetary/rate claim anywhere in the copy or in any computed field surfaced to the user — consistent with Out of Scope and AC29. The backend never computes or exposes a currency figure for this feature.
- `send_to_user`'s existing behavior for zero/dead subscriptions applies unchanged (feature-spec §27, "Missing push subscription" — no push sent, no error).

**The push body above and `slab_recommendation.explanation` (§16) are two different strings, both AC29-constrained, neither derived from the other.** The push copy is fixed verbatim per feature-spec §21 with zero interpolation — it never changes regardless of the user's numbers. `explanation` is generated by `evaluate_switch_recommendation` specifically for the read path, where `frontend-spec.md` §9 needs a sentence that references the actual meters/date (mirroring the existing `_nudge_text` pattern in `electricity_insights_service.py`) — e.g. `f"{active_label} is projected to reach its slab limit around {recommended_switch_date}. Switching to {standby_label} may help keep your usage in a lower slab."` Both strings are backend-owned, both are reviewed against the same "no currency, no guarantee" constraint, but they are not required to be textually identical — the push notification's job (grab attention, fixed and predictable) and the in-app card's job (explain the specific numbers) are different enough that forcing one shared string would either make the push template-driven (contradicting §21's "no interpolation") or make the card generic (contradicting `frontend-spec.md`'s requirement for specific units/dates).

---

## 14. Deduplication

Reuses `ReminderDispatchLog` and its existing `(user_id, sent_on, slot)` unique constraint — no schema change (§3).

**Slot naming**: `meter_slab_recommendation_{anchor_reading_id}`, where `anchor_reading_id` is the active meter's `last_billed_reading_id` (a UUID, stringified). This directly satisfies feature-spec §23's suggested convention and its requirement that "the recommendation lifecycle should be distinguishable between different billing anchors":

- When `Meter.last_billed_reading_id` changes (a new bill is logged), the slot string changes automatically — the new billing period starts a fresh notification lifecycle with no manual reset needed (AC24).
- When the active meter changes (a switch happened) to a meter with a *different* (or null) `last_billed_reading_id`, the slot again changes automatically, or the anchor-missing gate (§5, feature-spec §7) simply stops evaluation until that meter has its own bill — either way, the previous meter's obsolete recommendation state is never consulted again (AC23).

**Confirmed dedup policy: daily-only, no cooldown.** Every dispatch run re-evaluates the recommendation from scratch (§19's "re-evaluate the current state on every dispatch"). The **only** guard against duplicate sends is the existing `(user_id, sent_on, slot)` unique constraint — the same "already sent today?" pre-check `dispatch_due` performs (§4 query 10): if a row already exists for `(user_id, sent_on=today, slot)`, skip; otherwise, if the recommendation criteria are satisfied, send and log.

There is **no** separate multi-day cooldown or escalation layer. As long as the underlying opportunity remains valid (§10's `recommend_switch` stays true) and the recipient hasn't already been notified *today*, the recipient is notified again on the next dispatch — including the next calendar day. This is a confirmed product decision: feature-spec §22's "should not blindly send a notification every day" is satisfied here in its literal, narrowest sense — at most one notification per recipient per calendar day (exactly what the existing unique constraint already guarantees) — not by adding a longer suppression window on top of it. "Stop recommending if the user switches" and "stop recommending if the opportunity disappears" (§22) are both satisfied structurally, since the criteria are recomputed fresh every run with no cached state; there is no separate "escalation" trigger to implement, because re-notification is already allowed on every subsequent day the opportunity persists.

As with `dispatch_due`/`dispatch_water_due`: the `ReminderDispatchLog` row is only written **after** `PushService.send_to_user` reports `sent_count > 0` — a fully-failed push (zero successful deliveries) does not consume the slot, satisfying AC26 by the same mechanism already in production for the other two dispatch operations.

**Everything in this section (§14) describes the dispatch path only.** `ReminderDispatchLog` — the slot-naming convention, the daily uniqueness check, the "already notified" state — has no bearing whatsoever on the read path (§16). `GET /api/v1/electricity/insights` returning `slab_recommendation` is not a "notification" and does not consult, read, or write `ReminderDispatchLog` in any way. This is intentional and important: a recipient who was already pushed today (and therefore skipped by `dispatch_meter_slab_recommendation` on a later run today) still sees `slab_recommendation` populated on `/insights` if the underlying opportunity is still valid — the card is not suppressed just because a push already fired. Conversely, a recommendation that exists on `/insights` doesn't mean a push was (or will be) sent — that still depends on the independent dedup state in `ReminderDispatchLog`. The two surfaces answer two different questions ("is this still a valid recommendation right now" vs. "have we already pushed about this today") using the same underlying evaluation but genuinely independent gating on top of it.

---

## 15. Timezone Handling

All day-based calculations — elapsed days since anchor, the 10-day evaluation boundary, billing-period-end estimation, and the dedup `sent_on` comparison — use `settings.reminder_timezone`, per feature-spec §24 and AC25.

**Recommendation: use `app.core.timezone.local_today()` / `local_now()`, not the inline `datetime.now(ZoneInfo(settings.reminder_timezone))` pattern `push_service.py`'s existing `dispatch_due`/`dispatch_water_due` use.** Both patterns are live in the codebase today (see the explore findings); this spec picks the `app/core/timezone.py` helper module for **new** code specifically because:

- It's directly monkeypatchable in tests (`monkeypatch.setattr("app.core.timezone.local_now", ...)`), exactly as `tests/test_gym.py` already does — this is the only existing precedent in the repo for freezing "today" in a test, and the new dispatch function's 10-day-boundary tests (AC6/AC7) need exactly that capability.
- It centralizes the `ZoneInfo(settings.reminder_timezone)` construction rather than repeating it inline.

This is a forward-looking implementation choice for the *new* code only — **`push_service.py`'s existing `dispatch_due`/`dispatch_water_due` are not touched or refactored** to match; that would be scope creep beyond this feature.

One existing-code detail worth flagging explicitly: `get_insights`'s `days_since_bill` field (`electricity_insights_service.py:192,218`) is computed via naive `datetime.utcnow().date()`, **not** `settings.reminder_timezone`. That field must **not** be reused for this feature's elapsed-days/10-day-boundary calculation — the new code computes its own timezone-aware elapsed-days value independently (per AC25), rather than importing a UTC-naive figure from the insights path. This is not a bug to fix (out of scope, application code untouched) — just a reason the new code can't shortcut through `get_insights`.

---

## 16. API Contract Required by the Frontend

**No new endpoint.** `frontend-spec.md`'s consistency pass established that its recommendation card cannot be built from the push notification alone (a notification is fire-and-forget; it can't be re-read when the user later opens or reopens the page). The resolution — confirmed, not proposed — is to extend the **existing** `GET /api/v1/electricity/insights` response with one new, nullable field, computed by the exact same evaluation logic §5-§11 already define. This closes what was Open Implementation Question §24 item 1.

### 16.1 Two contracts change; both are additive

**A. `POST /api/v1/push/dispatch`'s response body** — unchanged from the earlier draft of this spec:

```
POST /api/v1/push/dispatch?token=<dispatch_token>

200 OK
{
  "processed_users": <int>,   // sum across all three dispatch operations, as today
  "sent": [
    ...,
    {"user_id": "<uuid>", "slot": "meter_slab_recommendation_<anchor_reading_id>", "subscriptions": <int>}
  ],
  "errors": [ ... ]            // unchanged shape: {"type": ..., "status"?: ..., "detail": ...}
}
```

No request shape change (still the existing `token` query param), no auth mechanism change (AC27 — the existing `settings.dispatch_token` check in `push.py:38` is untouched), no change to `processed_users`'s semantics beyond adding this feature's own candidate count into the same running sum the other two operations already contribute to.

**B. `GET /api/v1/electricity/insights`'s response body** — new field, additive:

```
GET /api/v1/electricity/insights   (unchanged path, unchanged auth — Bearer JWT via get_current_user,
                                     unchanged router-level Depends(require_feature("electricity_tracker")))

200 OK
{
  "meters": [ ...unchanged, see electricity_insights_service.get_insights... ],
  "slab_recommendation": SlabRecommendationResponse | null
}
```

`SlabRecommendationResponse` (new Pydantic model, `app/schemas/electricity.py`) — every field is a value `evaluate_switch_recommendation` (§1) already computes as part of §5-§11's pipeline; nothing here is a new calculation:

| Field | Type | Source (already defined in this spec) |
|---|---|---|
| `active_meter_id` | `UUID` | The active `Meter.id` (§2 — `resolve_active_meter_id`) |
| `active_meter_label` | `str` | Active `Meter.label` |
| `standby_meter_id` | `UUID` | The standby `Meter.id` (the other of the user's two accessible meters) |
| `standby_meter_label` | `str` | Standby `Meter.label` |
| `active_cumulative_units` | `float` | `cumulative_active` (§5/§9 — `compute_cumulative`) |
| `active_next_slab_min` | `float` | `next_slab_min` for the active meter's bracket (§8 — `_next_slab_min`); never `None` when a recommendation exists, since §7 already skips (returns no recommendation) when the active meter has no further boundary to project toward |
| `active_operational_threshold` | `float` | `operational_threshold_active` = `active_next_slab_min - settings.meter_slab_safety_buffer_units` (§8) |
| `standby_cumulative_units` | `float` | `cumulative_standby` (§9) |
| `standby_next_slab_min` | `float \| None` | `next_slab_min` for the standby meter's bracket (§8); nullable because the standby meter can legitimately be in its own open-ended top slab (§9's table) |
| `standby_operational_threshold` | `float \| None` | `operational_threshold_standby` (§8); nullable for the same reason as above |
| `recommended_switch_date` | `date` (ISO, e.g. `"2026-08-26"`) | `projected_operational_threshold_date` (§11) — identical value used for §11's own recommended-switch-date calculation; never independently computed a second time |
| `explanation` | `str` | New, generated inside `evaluate_switch_recommendation` — see §13's clarification distinguishing this from the fixed push copy |

`slab_recommendation` is `null` whenever `evaluate_switch_recommendation(db, user_id, today)` returns `None` — i.e., **exactly** the same `recommend_switch == False` condition that would also make `dispatch_meter_slab_recommendation` skip this user, computed by calling the identical function, not a re-derived approximation of it. No approved business rule from §5-§14 changes to accommodate this — the read path adds a caller, not a new decision.

### 16.2 Why this is not a second algorithm

`get_insights(db, user_id)` (`electricity_insights_service.py:167`) is extended (additively — its existing per-meter loop and every existing field it returns are untouched) with one new call:

```python
today = local_today()  # app.core.timezone — see §15's rationale for using this over naive utcnow()
recommendation = evaluate_switch_recommendation(db, user_id, today)
return {"meters": [...], "slab_recommendation": recommendation}  # recommendation is already None or a fully-populated result
```

`evaluate_switch_recommendation` is the **same function** `PushService.dispatch_meter_slab_recommendation` calls once per candidate (§1). Both callers pass it a `db` session, a `user_id`, and "today," and take its return value as-is:

- The dispatch path additionally checks `ReminderDispatchLog` and calls `PushService.send_to_user` — bookkeeping *around* the decision, not part of it.
- The read path additionally serializes the result into `SlabRecommendationResponse` — a shape transformation, not part of the decision either.

Neither caller re-implements, re-checks, short-circuits, or overrides any part of §5-§11's logic. This is the concrete mechanism satisfying "reuse the exact same recommendation calculation logic already defined in this Backend Spec" and "do not create a second recommendation algorithm for the API."

### 16.3 Fresh evaluation, independent of dispatch/dedup state

Per §14's closing paragraph: the read path never queries `ReminderDispatchLog`. Every call to `GET /api/v1/electricity/insights` re-runs `evaluate_switch_recommendation` from the current database state at request time — there is no caching of the result between requests and no dependency on whether, or when, a push was last sent for this user. A user who already received today's push still sees `slab_recommendation` populated if the opportunity remains valid; a user who will never receive a push (e.g., no push subscription registered — feature-spec §27's "Missing push subscription" edge case) still sees `slab_recommendation` populated on `/insights` if they otherwise qualify, since that edge case only affects `send_to_user`'s delivery step, which the read path never calls.

---

## 17. Dispatch Integration

`app/api/push.py`'s `dispatch()` route gains a third call, following the exact merge pattern already used for the other two:

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

Same shared-secret `dispatch_token` check (§13's requirement, AC27) — unchanged, runs once for the whole request as today, gating all three operations together (not per-operation).

`PushService.dispatch_meter_slab_recommendation(db)` returns the same `{"processed_users": int, "sent": [...], "errors": [...]}` shape `dispatch_due`/`dispatch_water_due` return, for the merge above to work without special-casing.

This dispatch wiring is entirely independent of §16's read-path addition — `POST /api/v1/push/dispatch` and `GET /api/v1/electricity/insights` are two separate routes in two separate files, each calling `evaluate_switch_recommendation` on their own terms (§16.2). Adding the read path required no change to this section's dispatch wiring, and vice versa.

---

## 18. Feature-Flag Integration

The electricity module's existing per-user flag, `FeatureFlag(feature_key="electricity_tracker")`, gates this feature too (feature-spec §26, AC28) — same flag, no new `feature_key` value.

Because the dispatch path runs outside any HTTP request (no `Depends(...)`, no `get_current_user`), `require_feature`'s dependency-factory form (`app/api/deps.py:68`) cannot be reused directly — it's built to raise `HTTPException` inside a FastAPI request cycle. The new dispatch function instead performs the equivalent query directly (§4 query 2), skipping a candidate user (not raising) when the flag is missing or `enabled=False` — same default-deny semantics as `require_feature`, just expressed as a `continue` in a loop instead of a `403`.

This check runs **per candidate user** (owner and shared users alike), consistent with §12's "evaluate every candidate independently" design — a shared user without the flag enabled on their own account is skipped even if the owner has it enabled, and vice versa.

**The read path (§16) needs none of this manual querying.** `GET /api/v1/electricity/insights` is already declared on a router with `dependencies=[Depends(require_feature("electricity_tracker"))]` (`electricity.py:22-26`, pre-existing, unchanged) — by the time `get_insights`/`evaluate_switch_recommendation` runs, FastAPI has already rejected the request with a `403` if the flag isn't enabled for the requesting user. Same flag, same default-deny semantics as the dispatch path, enforced by a different (and, for an HTTP route, more idiomatic) mechanism — not a second flag-gating implementation.

---

## 19. Error Handling and Edge Cases

Direct mapping from feature-spec §27:

| Edge case | Backend behavior |
|---|---|
| Zero meters | Candidate not in pool (no `Meter`/`MeterShare` row) — never iterated |
| One meter | `accessible_meter_ids` returns length 1 → skip (§4 eligibility gate) |
| More than two meters | `accessible_meter_ids` returns length > 2 → skip |
| No billed reading | `Meter.last_billed_reading_id is None` on the active meter → skip before any projection math runs (§5) |
| Insufficient reading history | `overall_rate`/`recent_rate` unavailable or `cumulative_active_units <= 0` → skip (§7) |
| Zero consumption | Same guard as above (`cumulative_active_units <= 0`) |
| Active meter already beyond the next slab | `_next_slab_min(...)` returns `None` (open-ended top bracket) → skip; no claim of undoing recorded consumption is ever made since no notification fires |
| Both meters near their slab thresholds | §10's `remaining_capacity_standby > remaining_capacity_active` comparison naturally fails when both are near zero/negative → no recommendation |
| User switches after notification | Every dispatch run re-resolves `resolve_active_meter_id` fresh (no cached state) — if the new active meter's own anchor differs or is missing, the slot string changes or evaluation halts entirely (§14) |
| New billed reading | Slot string changes automatically (anchor-embedded) — new lifecycle, no explicit reset needed (AC24) |
| Different slab configurations | Both meters' `SlabThreshold` rows are queried and used independently — no shared-threshold assumption anywhere in the code (§9) |
| Duplicate billing dates | Billed `MeterReading` rows sharing a `reading_date` (e.g. logged/confirmed by more than one accessible user) are reduced to their distinct dates before interval calculation — never contribute a 0-day interval (§6, AC12b) |
| Missing push subscription | `send_to_user` returns `sent=0`, no error — dedup log not written, matching existing behavior |

Two additional technical edge cases not explicitly named in feature-spec §27 but reachable in practice:

- **Meter has zero `SlabThreshold` rows configured**: `bracket_for([], ...)` returns `None` → `_next_slab_min` returns `None` → treated identically to "already in the open-ended top slab" (skip). This can't be hit for a normally-configured meter (creation requires at least conceptually one bracket) but the code must not crash if it happens (e.g. a meter created via some future path with no slabs).
- **Concurrent dispatch runs racing on the same dedup slot**: `dispatch_due`/`dispatch_water_due` already have this latent gap today (no `try/except` around the `ReminderDispatchLog` insert; two overlapping cron calls that both pass the "already sent?" pre-check before either commits would have the second `db.commit()` raise `IntegrityError` on the unique constraint) — this spec **recommends**, for the new function specifically, wrapping that insert in `try/except IntegrityError: db.rollback()` and treating it as an already-sent no-op, rather than propagating a 500. This is a robustness improvement scoped to the new code only; it does not require touching `dispatch_due`/`dispatch_water_due`.

**Per-candidate isolation**: unlike `dispatch_due`/`dispatch_water_due` (which have no per-user `try/except` and would abort the entire batch, and the *other* dispatch operations queued after them in the same request, on any single user's unhandled exception), this spec recommends wrapping each candidate's full evaluation in `try/except Exception`, appending `{"type": ..., "user_id": ..., "detail": ...}` to `result["errors"]` and continuing to the next candidate. Electricity data (rate math, division, slab lookups) has materially more edge-case surface than the simple time-of-day comparisons `dispatch_due`/`dispatch_water_due` perform, so this is a deliberate strengthening for this feature, not a requirement inherited from existing code.

**Every edge case in the table above applies identically to the read path (§16).** `evaluate_switch_recommendation` is one function with one set of skip conditions; whichever of the above causes it to return `None` for the dispatch path causes the exact same `None` — and therefore `slab_recommendation: null` — for the read path, for the same user, in the same current state. There is no separate edge-case table to maintain for §16, because there is no separate evaluation to have edge cases in.

---

## 20. Backend Automated Tests

New file: `tests/test_meter_slab_recommendation.py`, following `tests/test_electricity.py`'s existing fixture/factory conventions (`client`, `auth_headers` from `conftest.py`; local `_enable_feature`, `_create_meter`, `_register_and_get_headers` helpers reused or imported).

Additional test infrastructure needed beyond what `test_electricity.py` already has:

- A way to create a **billed** reading directly (`is_billed_reading: true` in the existing `POST .../readings` body — no new endpoint needed, `ReadingCreateRequest` already supports this field).
- A way to freeze "today" for the 10-day-boundary and next-day re-notification tests (AC6/AC7, test 22b) — `monkeypatch.setattr("app.core.timezone.local_now", lambda: fixed_dt)` (or `local_today`), following `tests/test_gym.py:117-129`'s existing pattern. Per §15, this is exactly why the new code is specified to depend on `app.core.timezone` rather than push_service.py's inline `ZoneInfo` call.
- A way to invoke the dispatch function directly (`PushService.dispatch_meter_slab_recommendation(db)`) as a unit-style test in addition to (or instead of) going through `POST /api/v1/push/dispatch?token=...`, to avoid needing a real VAPID/push subscription for every scenario — a fake/mock `PushSubscription` row (or monkeypatching `pywebpush.webpush`) is still needed for any test asserting `sent_count > 0`, matching the fact that no push-mocking precedent exists in the repo today (per the explore findings, there are currently zero tests for `PushService`/`ReminderDispatchLog`/dispatch of any kind) — this feature's test suite would be the first to establish that pattern.

Required test cases, one row per acceptance criterion (§21 gives the full traceability table; this list is the test-case breakdown):

1. Exactly two accessible meters → evaluation proceeds (AC1)
2. Zero or one accessible meter → no notification (AC2)
3. More than two accessible meters → no notification (AC3)
4. Active meter resolved via `resolve_active_meter_id` in a switched state (AC4)
5. `last_billed_reading_id is None` → no notification (AC5)
6. Anchor 9 days old → no notification (AC6)
7. Anchor exactly 10 days old → evaluation proceeds (AC7)
8. Non-default slab config (e.g. 0-50-150-∞) drives the projection, not a hardcoded 100 (AC8)
9. Next slab 100, buffer 2 → operational threshold 98 (AC9)
10. Sufficient history → rate computed and projection produced (AC10)
11. Recent rate > overall rate → projection uses the recent (max) rate (AC11)
12. ≥ `settings.meter_slab_min_billing_intervals_for_estimate` historical intervals → median used (AC12)
12b. Duplicate billed dates `Jul 06, Jul 06, Jul 06, Aug 09, Aug 09` → distinct dates `Jul 06, Aug 09` → a single `34`-day interval, not `[0, 0, 34, 0]` → estimated billing period is not `0` days (AC12b) — the concrete regression guard for the real-data failure this revision fixes
12c. The feature-spec §2 worked example (active ≈60 units, standby ≈0 units, 100-unit boundary, 2-unit buffer) combined with a duplicate-dated billing history (as in AC12b) still produces a populated recommendation once the other eligibility conditions are satisfied — proves the distinct-date fix actually resolves the end-to-end suppression, not just the isolated interval calculation
13. Insufficient historical intervals → `settings.meter_slab_default_billing_period_days` fallback used (AC13)
14. Threshold projected before billing-period end → standby evaluated (AC14)
15. Standby has no meaningful headroom → no notification (AC15)
16. Standby has meaningful headroom → eligible for notification (AC16)
17. The literal A=98/B=99/5-days-remaining scenario → no notification (AC17)
18. Recommended switch date equals the projected safety-adjusted operational-threshold date exactly — no additional day buffer subtracted (AC18)
19. Owner receives the push (AC19)
20. Shared user (access to both meters) receives the push (AC20)
21. Owner + shared user notified/deduped independently — one succeeding and one already-deduped in the same run (AC21)
22. Second dispatch same day → no second push to the same recipient (AC22)
22b. Second dispatch on the **next** calendar day, opportunity still valid → recipient **is** notified again (confirms the no-cooldown, daily-only re-notification policy — a regression guard against accidentally reintroducing a multi-day suppression window)
23. User switches meters between two dispatch runs → second run evaluates the new active meter, not the stale one (AC23)
24. New billed reading changes the anchor → new notification lifecycle begins even if the old one was already "used" (AC24)
25. Non-UTC `reminder_timezone` (e.g. `Asia/Kolkata`) shifts the 10-day boundary as expected (AC25)
26. `send_to_user` returns `sent=0` (simulated push failure) → dedup slot not consumed, next run retries (AC26)
27. `POST /api/v1/push/dispatch` without/with wrong token → 401, no evaluation performed (AC27)
28. `electricity_tracker` flag disabled for a candidate → that candidate skipped entirely (AC28)
29. Assert the sent notification body/title never contains a currency symbol or the word "save"/"saving" — a cheap regression guard for AC29 (belt-and-suspenders on top of the fact that the copy is a fixed constant with no interpolation)

Plus targeted edge-case tests: zero `SlabThreshold` rows on a meter; zero consumption; active meter already in the open-ended top slab; a same-day duplicate reading (recent-rate division guard).

Read-path tests (§16), new for this revision:

30. `GET /api/v1/electricity/insights` for a user with a valid recommendation returns `slab_recommendation` populated with every field in §16.1's table, matching exactly what `dispatch_meter_slab_recommendation` would have computed for the same DB state (assert both call sites produce identical values from a shared fixture — the concrete regression guard for "no second algorithm").
31. Same call for a user with `recommend_switch == False` (any of the skip conditions from §19) returns `slab_recommendation: null`.
32. A user who was already sent today's push (a `ReminderDispatchLog` row exists for today) still gets `slab_recommendation` populated on `/insights` if the opportunity remains valid — proves the read path doesn't consult `ReminderDispatchLog` (§16.3).
33. A user with the `electricity_tracker` feature flag disabled gets a `403` from the router-level dependency before `get_insights` ever runs — no `500`, no partial response (§18).
34. `GET /api/v1/electricity/insights`'s existing `meters` array and its existing fields are byte-for-byte unaffected by this change, for a user with no recommendation and for a user with one — regression guard against the additive change accidentally altering existing response shape.
35. `monkeypatch.setattr(settings, "meter_slab_safety_buffer_units", <other value>)` (and likewise for the other three fields) changes `evaluate_switch_recommendation`'s output accordingly, for both the dispatch path and the read path — proves the four parameters are actually read from `Settings` at call time, not baked in as constants, following the same monkeypatch convention `tests/test_gym.py` already uses for `reminder_timezone` (§22).

---

## 21. Backend Acceptance Criteria Mapped to the Feature Spec

| AC | Feature-spec requirement | Backend spec section(s) |
|---|---|---|
| AC1 | Exactly two meters → evaluate | §4 query 3, §19 |
| AC2 | Zero/one meter → skip | §4 query 3, §19 |
| AC3 | >2 meters → skip | §4 query 3, §19 |
| AC4 | Active meter via `resolve_active_meter_id` | §2, §4 query 4 |
| AC5 | No billing anchor → skip | §5, §19 |
| AC6 | <10 days → skip | §7, §22 |
| AC7 | ≥10 days → evaluate | §7, §22 |
| AC8 | Uses configured slabs, no hardcode | §8, §9, §16.1 (surfaced in `active_next_slab_min`/`standby_next_slab_min`) |
| AC9 | Buffer 2 → threshold 98 | §8, §16.1 (surfaced in `active_operational_threshold`/`standby_operational_threshold`) |
| AC10 | Rate → projection | §7 |
| AC11 | Recent > overall → use recent (max) | §7 |
| AC12 | Median of historical intervals | §6 |
| AC12b | Duplicate billing dates collapse to distinct dates, no spurious 0-day intervals | §4 query 9, §6, §19 |
| AC13 | Fallback to default | §6 |
| AC14 | Threshold before billing end → evaluate standby | §10 |
| AC15 | No meaningful standby benefit → no send | §10, §16.1 (`slab_recommendation: null`) |
| AC16 | Meaningful standby benefit → eligible | §10, §16.1 (`slab_recommendation` populated) |
| AC17 | Both near threshold → no blind switch | §10 (worked example), §16.1 (`slab_recommendation: null` for the same scenario) |
| AC18 | Recommended switch date | §11, §16.1 (`recommended_switch_date`) |
| AC19 | Owner notified | §12, §13 |
| AC20 | Shared user notified | §12, §13 |
| AC21 | Independent recipients/dedup | §12, §14 |
| AC22 | Daily dedup | §14 |
| AC23 | Re-evaluate on switch | §14, §19 |
| AC24 | New billing anchor → new lifecycle | §14, §19 |
| AC25 | Timezone-aware day math | §15 |
| AC26 | Push failure doesn't consume slot | §14 |
| AC27 | Dispatch auth unchanged | §16.1, §17 |
| AC28 | Feature-flag gated | §18, §16.1 (router-level gate, no manual query needed for the read path) |
| AC29 | No monetary claim | §13, §16.1 (`explanation` field held to the same constraint as the push copy) |

All 29 acceptance criteria, plus AC12b (new in this revision), have a corresponding backend design element and a corresponding test case in §20 (including tests #30-#35 from the read-path/Settings revisions, and #12b/#12c from this revision's duplicate-billing-dates fix). Implementation Principles 1-8 (feature-spec §30) are addressed structurally throughout (§2 for 1-3, §8/§9 for 4, §13 for 5-6, §12/§14 for 7, §14/§19 for 8). Principle 9 (spec + AC as definition of done) and 10 (tests before completion) are procedural, not architectural — satisfied by treating §20/§21 as the completion gate for the eventual implementation PR, not by anything in this document alone.

---

## 22. Configurable Parameters (backend-specific)

**Confirmed: all four parameters are `app/core/config.py` `Settings` fields, not module-level constants.** This supersedes the previous revision's choice (which followed the `MAX_METERS_PER_USER`/`APPROACHING_FRACTION` electricity-module precedent). The precedent followed now is `reminder_timezone`/`dispatch_token`/`access_token_expire_minutes` — a one-to-two-line comment above each field explaining the default, sourced from `.env`/Render env vars, with every field defaulted so no `.env` change is required to deploy with current behavior, and safely monkeypatchable in tests via `monkeypatch.setattr(settings, "field_name", value)` exactly as `tests/test_gym.py` already does for `reminder_timezone`.

Rationale for this choice: unlike `MAX_METERS_PER_USER` or `APPROACHING_FRACTION` (fixed product shape decisions unlikely to need runtime tuning), these four values are genuinely operational knobs — how conservative the evaluation window is, how large a safety margin to keep, how much billing history to trust — that ops/product may reasonably want to adjust per-environment or during rollout without waiting on a code deploy, matching exactly the kind of value `reminder_timezone` and `dispatch_token` already represent in this codebase.

Additive fields for `Settings` (illustrative — final comment wording is an implementation detail, not part of this spec):

```python
# How many calendar days must elapse since the billing anchor before the
# meter-slab-recommendation evaluation begins (feature-spec §8).
meter_slab_min_evaluation_days: int = 10

# Safety margin (in units) kept below a meter's next slab boundary when
# computing its operational threshold — the only safety margin used
# anywhere in the meter-slab-recommendation feature (feature-spec §11).
meter_slab_safety_buffer_units: float = 2

# Fallback assumed billing-period length (in days) when too few historical
# billed readings exist to compute a reliable median (feature-spec §14).
meter_slab_default_billing_period_days: int = 30

# Minimum number of historical billing intervals required before trusting
# their median over the default billing-period-length fallback above.
meter_slab_min_billing_intervals_for_estimate: int = 2
```

`meter_slab_recommendation_service.py`'s functions read these via `from app.core.config import settings; settings.meter_slab_*` at call time (never re-instantiated, never cached into a local module-level copy) — the same access pattern every other consumer of `Settings` in this codebase already uses.

This is the **complete** list of configurable parameters this feature needs — no switch-safety-days buffer, no standby-headroom floor, and no re-notification cooldown constant, per the confirmed decisions in this revision (§23).

| Settings field | Default | Type | Status |
|---|---|---|---|
| `meter_slab_min_evaluation_days` | `10` | `int` | Value fixed by feature-spec §8/§29; storage mechanism confirmed as a `Settings` field (this revision) |
| `meter_slab_safety_buffer_units` | `2` | `float` | Value fixed by feature-spec §11/§29 — the **only** safety margin in this feature; storage mechanism confirmed as a `Settings` field (this revision) |
| `meter_slab_default_billing_period_days` | `30` | `int` | Value fixed by feature-spec §14/§29; storage mechanism confirmed as a `Settings` field (this revision) |
| `meter_slab_min_billing_intervals_for_estimate` | `2` | `int` | Confirmed product decision (previous revision); storage mechanism confirmed as a `Settings` field (this revision) |

---

## 23. Design Choices and Confirmed Product Decisions

### 23.1 Design choices made directly from feature-spec wording (not open questions)

For traceability, these interpretations were resolvable from the feature spec's own text/examples and are **not** listed as open questions:

- Recipients fall out of independent per-user evaluation rather than a meter→recipient fan-out (§12, from "recipients must be evaluated independently").
- "Full handoff" means the active meter's `projection_rate` is reused to project the standby meter's post-switch trajectory, rather than trying to derive an independent standby rate (§9, from the AC17 worked example needing a like-for-like comparison).
- `remaining_capacity_standby > remaining_capacity_active` implements all three of §17's stated priorities as one rule (§10, verified against both worked examples in §2 and §16 of the feature spec).
- `floor()` for the fractional-days-to-calendar-date conversion, biasing earlier (§7), consistent with the safety-buffer philosophy stated throughout §11.
- Billing-anchor-embedded slot naming for dedup, exactly as feature-spec §23 suggests (`meter_slab_recommendation_{anchor_reading_id}`).

### 23.2 Confirmed product decisions (this revision)

These were previously listed as open questions and have now been explicitly confirmed, superseding the earlier draft:

- **Billing-period estimation scope**: historical billing intervals are computed from `is_billed_reading=True` readings pooled across **both** of the user's accessible meters, not the active meter alone (§6).
- **`meter_slab_min_billing_intervals_for_estimate` defaults to `2`**: at least 2 historical intervals (3 pooled billed readings) are required before trusting the median; otherwise `meter_slab_default_billing_period_days` (30) is used (§6).
- **No `SWITCH_SAFETY_DAYS`, no separate calendar-day switch buffer**: removed entirely. `meter_slab_safety_buffer_units = 2` is the sole safety margin in this feature. The recommended switch date is exactly the projected safety-adjusted operational-threshold date (§11).
- **No `MIN_STANDBY_HEADROOM_UNITS`**: removed entirely. Any strictly-greater remaining safe capacity on the standby meter (`remaining_capacity_standby > remaining_capacity_active`) counts as a meaningful opportunity — no additional arbitrary floor is layered on top (§10).
- **No re-notification cooldown**: removed entirely. The recommendation is re-evaluated on every dispatch; the only send-frequency limit is the existing daily `(user_id, sent_on, slot)` uniqueness — a recipient can be notified again on the very next calendar day if the opportunity is still valid (§14).
- **A read surface is confirmed needed, resolved by extending `/insights` rather than adding a new endpoint**: `GET /api/v1/electricity/insights` gains a `slab_recommendation` field (§16), computed by the same `evaluate_switch_recommendation` function the dispatch path already uses — no second algorithm, no new endpoint, `ReminderDispatchLog` plays no part in this field's value. This closed what was Open Implementation Question §24 item 1 in the prior revision.
- **The four feature parameters are `Settings` fields, not module-level constants**: `meter_slab_min_evaluation_days`, `meter_slab_safety_buffer_units`, `meter_slab_default_billing_period_days`, and `meter_slab_min_billing_intervals_for_estimate` are added to `app/core/config.py`'s `Settings` class, env-var-configurable, following the `reminder_timezone`/`dispatch_token` precedent (§22). This supersedes the prior revision's choice of the `MAX_METERS_PER_USER`/`APPROACHING_FRACTION` module-constant precedent, and closes what was Open Implementation Question §24's last remaining item.
- **Billing intervals are computed from distinct billed dates, not raw billed rows** (this revision, §6/§4 query 9): confirmed as a correctness requirement, not an optional cleanup, after real data showed duplicate-dated billed readings (multiple accessible users confirming the same real-world bill) collapsing the estimated billing period to `0` days and permanently suppressing an otherwise-valid recommendation. This does not change the minimum-2-intervals rule, the 30-day fallback, or the both-meters pooling scope — it only changes what counts as one "historical interval."

---

## 24. Open Implementation Questions

**None.** Every question raised across this spec's revisions — billing-period estimation scope, the minimum-intervals threshold, the switch-date buffer, the standby-headroom floor, the re-notification/cooldown policy, whether a read surface is needed, and whether the four configurable parameters live in `Settings` or as module constants — has been explicitly confirmed. See §23.2 for the consolidated list of confirmed decisions and the section each one lives in. This spec is implementation-ready with no outstanding product/architecture sign-off needed.
