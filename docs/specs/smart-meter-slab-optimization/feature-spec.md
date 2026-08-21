# Smart Meter Slab Optimization

Status: implemented and deployed (`wellness-backend` `main` via PR #40; `wellness-tracker` `feature/smart-meter-slab-optimization`). None of the business rules or acceptance criteria below changed after deployment. Two issues were found and fixed post-launch, both purely mechanical, not product decisions: a duplicate-billing-dates bug in the billing-period estimator (AC12b — see `backend-spec.md` Revision note 4) and a post-merge incident that dropped required `Settings` fields/imports from `main` (see `backend-spec.md` Revision note 5 and `implementation-plan.md` §17).

## 1. Overview

Build a proactive smart meter-switch recommendation that analyzes consumption across a user's two accessible meters and recommends switching when doing so can improve the distribution of consumption across slab thresholds during the current billing period.

The feature should use existing electricity reading, billing-anchor, meter-switch, slab, sharing, and push-notification infrastructure wherever possible.

The feature replaces the previously proposed generic "15-day overdue meter switch reminder."

---

## 2. Business Objective

Customers can have two meters with slab-based electricity rates.

The objective is to help customers avoid unnecessary movement into a higher usage slab by intelligently determining when switching the active meter may provide a better slab outcome.

For example:

* Meter A = 60 units
* Meter B = 0 units
* Next slab boundary = 100 units

If Meter A is consuming approximately 6 units/day, it may reach the next slab well before the expected end of the billing period. Switching to Meter B before that happens may allow future consumption to remain within the lower slab on Meter A.

Another example:

* Meter A = 98 units
* Meter B = 99 units
* 5 days remaining

The system must recognize that neither meter has meaningful safe headroom and must not blindly recommend switching from A to B.

The recommendation must consider both meters.

---

## 3. Scope

### In Scope

* Exactly two accessible meters.
* Active-meter resolution using existing `resolve_active_meter_id`.
* Billing-period anchor using `Meter.last_billed_reading_id`.
* Current-period consumption using existing `compute_cumulative`.
* Slab evaluation using existing `bracket_for` and `_next_slab_min`.
* Consumption-rate estimation.
* Projection of when the active meter reaches its operational slab threshold.
* Estimation of the user's typical billing-period duration from historical billed readings.
* Evaluation of the standby meter.
* Calculation of whether switching provides a meaningful slab-optimization opportunity.
* Calculation of a recommended switch date.
* Push notification to eligible recipients.
* Owner and eligible `MeterShare` users as recipients.
* Notification deduplication.
* Timezone-aware evaluation.
* Integration with `/api/v1/push/dispatch`.

### Out of Scope

* Actual electricity tariff/rate calculations.
* Currency or monetary savings calculations.
* Adding `rate_per_unit` or other pricing data to `SlabThreshold`.
* Changes to the existing meter-switch UI.
* Changes to `create_switch_event`.
* Changes to how electricity readings are recorded.
* Guaranteeing an exact future bill amount.
* Guaranteeing that switching will reduce the customer's bill.

The system may state that switching **may help maintain a lower slab**, but must not claim a specific monetary saving.

---

## 4. User Eligibility

Evaluate each user independently.

A user is eligible for the feature only when:

1. The user has exactly two accessible meters.
2. Accessible meters are determined using the existing `accessible_meter_ids`.
3. The active meter is resolved using `resolve_active_meter_id`.
4. A valid billing anchor exists through `Meter.last_billed_reading_id`.
5. Sufficient reading history exists to make a meaningful consumption projection.
6. The current evaluation occurs at or after the minimum evaluation point.

Users with zero or one accessible meter are skipped.

Users with more than two accessible meters are also skipped.

---

## 5. Accessible Meters

Use:

`accessible_meter_ids(db, user_id)`

Accessible meters include:

* meters owned by the user;
* meters shared with the user through `MeterShare`.

Do not use `Meter.user_id` alone to determine the user's accessible meter set.

---

## 6. Active Meter

Use the existing:

`resolve_active_meter_id(db, user_id)`

The existing active-meter behavior must not be duplicated or reimplemented.

The resolved active meter is the meter whose consumption is primarily evaluated for the recommendation.

The other accessible meter is the standby/alternative meter.

---

## 7. Billing Period Anchor

The current billing period is defined by the existing `Meter.last_billed_reading_id`.

Resolve:

`Meter.last_billed_reading_id → MeterReading`

The referenced `MeterReading.reading_date` is the billing-period anchor date.

If `last_billed_reading_id` is null:

* Do not treat the first-ever reading as a billed reading.
* Do not make a slab-optimization push recommendation.
* Skip the recommendation until a billed reading exists.

This is important because the existing `compute_cumulative` helper can fall back to the first-ever reading, but that fallback must not be interpreted as an actual billing date for this feature.

---

## 8. Minimum Evaluation Point

The system should begin evaluating the current billing period after approximately 10 calendar days have elapsed from the billing anchor.

10 days is the **first evaluation point**, not an unconditional notification trigger.

The system must not send a notification merely because 10 days have passed.

Instead:

* before 10 days → no evaluation/notification;
* at or after 10 days → perform the slab-optimization analysis;
* notification is sent only when the recommendation criteria are satisfied.

Use calendar days and `reminder_timezone`.

---

## 9. Current Consumption

Reuse the existing:

`compute_cumulative(db, meter)`

This currently calculates:

`latest.reading_value - anchor.reading_value`

The feature must not create a second definition of current-period consumption.

The result represents units consumed since the billing anchor.

---

## 10. Slab Thresholds

Use the meter's existing `SlabThreshold` configuration.

Do not hard-code `100` units.

For example, if the configured slabs are:

* 0–100
* 100–200
* 200+

then the next slab boundary is 100.

If the configured slabs change, the recommendation logic must adapt automatically.

Use the existing:

* `bracket_for()`
* `_next_slab_min()`

where appropriate.

### Current product assumption

Both meters currently use the same slab configuration.

However, implementation should use each meter's configured thresholds rather than assuming identical thresholds in code.

This preserves future flexibility.

---

## 11. Safety Buffer

The system must maintain a safety margin below the next slab boundary.

Default:

`SLAB_SAFETY_BUFFER_UNITS = 2`

For a next slab boundary of 100:

`operational_threshold = 100 - 2 = 98`

Therefore, the system should plan around reaching 98 rather than waiting until 100.

The safety buffer exists to account for:

* baseline meter/electrical consumption;
* consumption between readings;
* reading timing differences;
* prediction uncertainty;
* unexpected consumption.

The buffer must be configurable.

Do not hard-code `98`.

### Example

```text
Next slab boundary = 100
Safety buffer = 2
Operational threshold = 98
```

---

## 12. Consumption Rate

The recommendation should use consumption velocity rather than a simple current-units threshold.

Calculate an overall consumption rate using the current billing-period consumption and elapsed billing-period days.

Conceptually:

`overall_rate = cumulative_units / elapsed_days`

Where sufficient historical readings exist, also calculate a recent consumption rate from the latest meaningful reading interval.

Conceptually:

`recent_rate = units_delta / days_between_readings`

Use the more conservative rate for projection:

`projection_rate = max(overall_rate, recent_rate)`

If a recent rate cannot be calculated reliably, use the overall rate.

If consumption is zero or the rate cannot be calculated meaningfully, do not create a projection-based recommendation.

---

## 13. Projected Operational-Threshold Date

Determine the active meter's next slab boundary and subtract the configured safety buffer.

Example:

```text
Current consumption = 60
Next slab = 100
Safety buffer = 2

Operational threshold = 98
Remaining safe capacity = 98 - 60 = 38
```

If the projection rate is 6 units/day:

```text
38 / 6 ≈ 6.3 days
```

The active meter is therefore projected to reach its operational threshold approximately 6 days from the current evaluation date.

---

## 14. Billing-Period Duration

There is no explicit billing-period entity in the current system.

Historical billing intervals can be reconstructed from:

`MeterReading`

where:

`is_billed_reading = true`

Use historical billed readings to estimate the user's typical billing interval when sufficient history exists.

### Duplicate billing dates

Multiple billed readings can share the same calendar `reading_date`. This happens legitimately — for example, a shared meter where more than one accessible user each logs or confirms a reading for the same real-world bill, or a bill re-entered on the same day it was first logged. These duplicates represent **one** billing date, not several.

Billing-interval estimation must use the **distinct set** of billed `reading_date` values (across both accessible meters), sorted chronologically, before computing intervals between them. A repeated date must never be treated as a second billing event, and must never manufacture an artificial 0-day interval.

Example:

```text
Raw billed dates:
Jul 06, Jul 06, Jul 06, Aug 09, Aug 09

Distinct dates:
Jul 06, Aug 09

Interval:
34 days
```

Without deduplication, the same raw dates would incorrectly produce intervals of `0, 0, 34, 0` — a median of `0` days, which collapses the estimated billing-period end to the billing anchor date itself and permanently suppresses the recommendation regardless of how urgent the actual consumption picture is. This is a correctness requirement, not an edge case to defer.

Prefer a median of historical billing intervals (computed between consecutive **distinct** dates) rather than a simple average, so that an unusually long or short billing period does not disproportionately affect the estimate.

Example:

```text
Historical intervals (between consecutive distinct billed dates):
29, 30, 30, 31, 45

Typical interval:
30 days
```

### Fallback

If insufficient historical billing data exists, use a configurable default:

`DEFAULT_BILLING_PERIOD_DAYS = 30`

The fallback must be treated as an estimate, not as the customer's confirmed billing cycle.

---

## 15. Billing-Period Risk

Estimate the expected end of the current billing period.

Compare:

* projected active-meter operational-threshold date;
* expected end of billing period.

A recommendation opportunity exists when the active meter is projected to reach its operational threshold before the expected end of the billing period.

Example:

```text
Today = Day 10
Estimated billing period = 30 days
Days remaining = 20

Active meter = 60 units
Operational threshold = 98
Projection rate = 6/day

Remaining safe capacity = 38
Projected threshold = ~6.3 days
```

The active meter is projected to reach its operational threshold around Day 16–17, significantly before the expected billing-period end.

This is a strong candidate for further standby-meter evaluation.

---

## 16. Standby Meter Evaluation

The system must evaluate the second meter before recommending a switch.

Do not recommend switching solely because the active meter is approaching its slab threshold.

Evaluate:

* standby meter's current-period consumption;
* standby meter's current slab;
* standby meter's next slab boundary;
* standby meter's safety-buffered operational threshold;
* standby meter's available headroom;
* projected consumption implications where sufficient data exists.

### Important example

```text
Meter A = 98
Meter B = 99
5 days remaining
```

Both meters have minimal headroom.

The system must not automatically recommend:

"Switch from A to B."

The standby meter does not provide a meaningful safe alternative.

---

## 17. Switching Recommendation

Recommend switching only when the analysis indicates that moving future consumption to the standby meter provides a meaningful slab-optimization opportunity.

The recommendation should prioritize:

1. Keeping as much consumption as possible below the operational slab threshold.
2. Avoiding unnecessary movement of a second meter into a higher slab.
3. Selecting the meter with greater safe headroom for future consumption.

The recommendation should not claim guaranteed savings.

---

## 18. Recommended Switch Date

The system should calculate a recommended switch date based on the projected operational-threshold date rather than simply using the 10-day evaluation date.

Conceptually:

`recommended_switch_date = projected_operational_threshold_date - SWITCH_SAFETY_DAYS`

The number of safety days should be configurable.

The system should not wait until the meter reaches 100.

Example:

```text
Current = 60
Operational threshold = 98
Projection rate = 6/day

Projected threshold ≈ 6.3 days away

Recommended switch date:
a configurable number of days before the projected threshold
```

The exact safety-day value should remain configurable and should not be embedded in the algorithm.

---

## 19. Notification Trigger

A notification should be sent only when all relevant conditions are satisfied:

1. User has exactly two accessible meters.
2. Active meter is resolved.
3. Active meter has a valid billed reading.
4. At least 10 days have elapsed since the billing anchor.
5. Current-period consumption can be evaluated.
6. A meaningful consumption projection can be calculated.
7. Active meter is projected to reach its safety-adjusted slab threshold before the expected billing-period end.
8. The standby meter provides a meaningful alternative/slab-optimization opportunity.
9. The recipient has not already received the applicable notification according to the deduplication rules.

---

## 20. Notification Recipients

Notify:

* the owner of the relevant meter;
* users who have access to the active meter through `MeterShare`.

Recipients must be evaluated independently.

Sending a notification to one recipient must not prevent another eligible recipient from receiving theirs.

Use the existing:

`PushService.send_to_user(db, user_id, title, body)`

for each recipient.

No new generic fan-out abstraction is required unless implementation reveals a clear need.

---

## 21. Notification Copy

### Title

**⚡ Consider switching meters**

### Body

**Your usage is approaching the next slab. Switching your active meter may help keep one meter within the lower usage slab.**

The notification must not claim:

* an exact rupee saving;
* guaranteed savings;
* guaranteed prevention of a higher slab.

Those claims require actual tariff/rate data, which does not currently exist.

---

## 22. Notification Frequency

The feature should not blindly send a notification every day.

The recommendation should be recalculated on subsequent dispatch runs.

After a notification:

* re-evaluate the current state;
* stop recommending if the user switches;
* stop recommending if the opportunity disappears;
* allow another notification when the recommendation becomes materially more urgent according to the configured notification policy.

The exact escalation/re-notification policy should be implemented as a configurable rule rather than hard-coded repeated daily notifications.

---

## 23. Deduplication

Reuse:

`ReminderDispatchLog`

The existing database uniqueness constraint:

`(user_id, sent_on, slot)`

must continue to prevent duplicate notifications to the same recipient on the same calendar day.

Use a dedicated slot namespace for this feature.

The recommendation lifecycle should also be distinguishable between different billing anchors so a new billing period does not incorrectly inherit the notification state of an older billing period.

A suitable implementation may encode the billing-anchor reading ID into the slot, for example:

`meter_slab_recommendation_{anchor_reading_id}`

The final implementation should preserve the existing database-level daily deduplication behavior.

---

## 24. Timezone

Use the existing:

`settings.reminder_timezone`

for all day-based calculations.

This includes:

* determining today's date;
* calculating elapsed calendar days since billing;
* determining the 10-day evaluation point;
* determining billing-period dates;
* daily notification deduplication.

Use calendar days, not business days.

---

## 25. Dispatch Integration

Add a new push-dispatch operation, for example:

`PushService.dispatch_meter_slab_recommendation(db)`

Integrate it into:

`POST /api/v1/push/dispatch`

alongside the existing dispatch operations.

Use the same shared-secret `dispatch_token` authentication.

The existing endpoint behavior and authentication mechanism must not be changed.

---

## 26. Feature Flag

The electricity module is already protected by:

`require_feature("electricity_tracker")`

The new functionality must remain behind the same electricity feature flag.

---

## 27. Edge Cases

### Zero meters

Skip.

### One meter

Skip because there is no alternative meter.

### More than two meters

Skip because this feature currently operates only on a two-meter model.

### No billed reading

Skip.

Do not interpret the first-ever reading as a billing anchor.

### Insufficient reading history

Do not make an unreliable projection.

### Zero consumption

No threshold-crossing projection is possible; skip recommendation.

### Active meter already beyond the next slab

Do not claim that switching will undo already-recorded slab consumption.

### Both meters near their slab thresholds

Do not recommend switching unless the standby meter provides meaningful additional headroom.

### User switches after notification

The next dispatch must recalculate the active meter and stop the previous recommendation if the opportunity no longer exists.

No explicit cancellation event is required.

### New billed reading

When `last_billed_reading_id` changes, the new billed reading becomes the billing anchor and the recommendation calculation starts a new billing-period lifecycle.

### Different slab configurations

Currently the product expects the same slabs on both meters, but the implementation should read each meter's configured slab thresholds rather than hard-code identical thresholds.

### Duplicate billing dates

Two or more billed readings (on either accessible meter) sharing the same calendar `reading_date` represent one billing date, not several. Billing-interval estimation must deduplicate by `reading_date` before computing intervals — a duplicate date must never produce a 0-day interval, and must never collapse the estimated billing-period end to the anchor date itself (§14).

### Missing push subscription

No push is sent. Existing `send_to_user` behavior applies.

---

# 28. Acceptance Criteria

### AC1 — Exactly two meters

Given a user has exactly two accessible meters, when the dispatch evaluates the user, then the feature evaluates the meter pair.

### AC2 — Zero or one meter

Given a user has zero or one accessible meter, when dispatch runs, then no recommendation notification is sent.

### AC3 — More than two meters

Given a user has more than two accessible meters, when dispatch runs, then no recommendation notification is sent.

### AC4 — Active meter

Given two accessible meters exist, the active meter is resolved using the existing `resolve_active_meter_id`.

### AC5 — No billing anchor

Given the active meter has no `last_billed_reading_id`, when dispatch runs, then no recommendation notification is sent.

### AC6 — Ten-day evaluation boundary

Given the billing anchor is less than 10 calendar days old, when dispatch runs, then no recommendation is sent.

### AC7 — Ten-day evaluation begins

Given the billing anchor is at least 10 calendar days old, when dispatch runs, then the system evaluates the slab-optimization conditions.

### AC8 — Existing slab configuration

Given a meter has configured slab thresholds, the recommendation uses those thresholds and does not hard-code 100 units.

### AC9 — Safety buffer

Given the next slab boundary is 100 and the configured safety buffer is 2 units, the operational threshold is 98 units.

### AC10 — Consumption rate

Given sufficient reading history exists, the system calculates a consumption rate and uses it to project when the active meter will reach its operational threshold.

### AC11 — Increasing consumption

Given the recent consumption rate is materially faster than the overall rate, the projection uses the configured conservative-rate strategy rather than ignoring the recent increase.

### AC12 — Billing-period estimation

Given sufficient historical billed readings exist, the system estimates the user's typical billing interval from historical billed-reading dates.

### AC13 — Billing-period fallback

Given insufficient historical billing intervals exist, the system uses the configured default billing-period duration.

### AC12b — Duplicate billing dates

Given billed readings exist on the dates `Jul 06, Jul 06, Jul 06, Aug 09, Aug 09`, when the system estimates the billing period, then it first reduces these to the distinct dates `Jul 06, Aug 09`, computes a single interval of `34` days between them, and the resulting estimated billing period is not `0` days. The duplicate dates must not produce additional 0-day intervals or corrupt the median toward 0.

### AC14 — Projected slab risk

Given the active meter is projected to reach its operational threshold before the expected end of the billing period, the system evaluates the standby meter for a switching opportunity.

### AC15 — No meaningful standby benefit

Given the standby meter does not provide meaningful additional slab headroom, no switch recommendation is sent.

### AC16 — Meaningful standby benefit

Given the active meter is approaching its operational threshold and the standby meter provides meaningful additional slab headroom, the recipient is eligible for a switch recommendation.

### AC17 — Both meters near threshold

Given Meter A is 98 units and Meter B is 99 units with 5 days remaining, the system must not blindly recommend switching from A to B.

### AC18 — Recommended switch date

Given a valid recommendation opportunity exists, the system calculates a recommended switch date using the projected operational-threshold date and configured safety parameters.

### AC19 — Owner notification

Given the owner is an eligible recipient and a recommendation is triggered, the owner receives the push notification.

### AC20 — Shared-user notification

Given a user has access to the active meter through `MeterShare` and is an eligible recipient, that shared user receives the push notification.

### AC21 — Independent recipients

Given the owner and one or more shared users are eligible, each recipient is evaluated and deduplicated independently.

### AC22 — Daily deduplication

Given a recipient has already received the recommendation on the current calendar day, another notification is not sent to that recipient on the same day.

### AC23 — State re-evaluation

Given a recommendation was previously sent and the user subsequently switches meters, the next dispatch re-evaluates the new active meter and does not continue the obsolete recommendation.

### AC24 — New billing period

Given a new billed reading becomes the meter's `last_billed_reading_id`, the new reading becomes the billing anchor for subsequent recommendation calculations.

### AC25 — Timezone

Given a configured `reminder_timezone`, all day-based calculations use that timezone.

### AC26 — Push failure

Given push delivery fails, the failed notification does not incorrectly consume the notification slot, consistent with the existing `ReminderDispatchLog` behavior.

### AC27 — Authentication

Given `/api/v1/push/dispatch` is called without the correct dispatch token, the dispatch operation is rejected.

### AC28 — Feature flag

Given the `electricity_tracker` feature is disabled, the recommendation functionality is not available.

### AC29 — No monetary claim

Given the system does not contain electricity tariff/rate data, the notification does not claim an exact monetary saving.

---

# 29. Configurable Parameters

The following values should be configurable rather than embedded directly in business logic:

* `MIN_EVALUATION_DAYS = 10`
* `SLAB_SAFETY_BUFFER_UNITS = 2`
* `DEFAULT_BILLING_PERIOD_DAYS = 30`
* switch/recommendation safety days
* recommendation re-notification/escalation policy

The initial values above are product defaults, not immutable constants.

---

# 30. Implementation Principles

1. Reuse existing electricity domain logic.
2. Do not duplicate active-meter resolution.
3. Do not create a second cumulative-consumption calculation.
4. Do not hard-code the 100-unit threshold.
5. Do not introduce tariff/cost calculations in this feature.
6. Keep the recommendation based on observable unit/slab behavior.
7. Keep owner and shared-user notifications independently deduplicated.
8. Re-evaluate the current state on every dispatch.
9. Treat the specification and acceptance criteria as the definition of done.
10. Add automated tests for every applicable acceptance criterion before considering the feature complete.
