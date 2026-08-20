# Smart Meter Slab Optimization — Frontend Spec

Status: draft, implementation-ready **except for one cross-spec dependency** (§3) that needs a small, explicitly-scoped addition to `backend-spec.md` before this can be built. Everything else in this document is implementation-ready against the frontend (`wellness-tracker`) codebase as it exists today.

**Revision note (consistency pass):** re-verified against the actual current implementation of `Electricity.tsx`, `ElectricitySwitchMeter.tsx`, and `electricityApi.ts` (read directly, not assumed). One design decision changed as a result: the recommendation card no longer renders its own "Switch Meter" button. The existing action-row button is reused unmodified instead of duplicated — see §10 for the reasoning. No other section changed in substance; this revision tightens §5, §6, §8, §10, and §19 to be explicit about exactly which existing files/markup are touched (only the new card's own markup and the `InsightsResponse` type) versus left completely alone (the per-meter cards, the action row, `ElectricitySwitchMeter.tsx`).

Source of truth: [`feature-spec.md`](./feature-spec.md) (product requirements) and [`backend-spec.md`](./backend-spec.md) (backend contract). This document does not reopen any decision made in either — it translates them into a concrete UI/data contract for the existing React + TypeScript + Vite PWA at `wellness-tracker`. Section numbers below are independent of both other documents' numbering.

This spec **does not** modify application code. Where it proposes an addition to an existing file (e.g., extending `InsightsResponse`), that is a plan for a future implementation PR, not code delivered by this document.

---

## 1. The One Cross-Spec Dependency (read this first)

`backend-spec.md` §16 concludes "no new HTTP endpoint is required" for V1, because the feature is dispatch/push-only — the push notification's title/body are the only surface the backend currently plans to expose. `backend-spec.md` §24 item 1 explicitly leaves open whether a dedicated read endpoint is wanted, deferring to product/frontend.

This frontend spec is that answer: **yes, a small read surface is needed.** The product requirements this document is asked to satisfy — a recommendation *card* showing current units, both meters' slab thresholds, a recommended switch date, and a human-readable explanation, all sourced from the backend rather than recomputed in React — cannot be built from a push notification's title/body alone. A push notification is a one-time, fire-and-forget event; it cannot be "re-read" later when the user opens the app, switches tabs, or reopens the page the next day. The UI needs a queryable snapshot of the recommendation, refreshed on every page load, exactly like every other piece of data on the Electricity page already is.

**Proposed resolution** (§3 gives the exact shape): extend the existing `GET /api/v1/electricity/insights` response with one new, nullable field, `slab_recommendation`, computed by the **same** `meter_slab_recommendation_service.py` functions `backend-spec.md` already specifies for the dispatch path (§6-§11 there) — not a second implementation of the algorithm, just a second caller of it. This is the minimal-diff option: one new field on a response shape the frontend already fetches every time it loads this page, versus a whole new endpoint and a second round trip.

This is flagged here, prominently, rather than silently assumed, because it requires a small backend change beyond what `backend-spec.md` currently commits to. The rest of this document is written against this proposed contract; if product/backend decides against it, the sections that depend on it (§5-§11, §14-§16) would need to be revisited.

---

## 2. Existing Frontend Patterns Reused

| Pattern | File | Reused for |
|---|---|---|
| Electricity page shell, load/error/loading branching, meter cards | `src/pages/Electricity.tsx` | Recommendation card is inserted into this exact page, same fetch, same three-branch (`loading`/`error`/content) structure — no new page (§5) |
| `getInsights()` + `InsightsResponse`/`InsightsMeter` types | `src/services/electricityApi.ts` | Extended (not replaced) with `slab_recommendation` (§4) |
| Shared `api` axios instance (auth header injection, 401 handling, cold-start retry) | `src/services/api.ts` | No changes needed — the extended `/insights` call already goes through this |
| `<SkeletonCard lines={n} />` | `src/components/Skeleton.tsx` | Loading state — no new skeleton variant (§13) |
| `.status-error` / retry-button pattern | `src/index.css`, used identically across `Electricity.tsx`, `Water.tsx`, etc. | Error state — no new error UI (§14) |
| `.electricity-nudge` (server-computed sentence, soft-tinted callout) | `Electricity.tsx` render of `meter.nudge_text`, styled in `src/index.css` | The exact styling precedent for the recommendation card's explanation text (§9) |
| `.electricity-meter-card`, `.electricity-badge-active`/`-standby`, `.electricity-slab-bar`/`-fill`/`-labels`, `--electricity-copper`/`--electricity-copper-bg` | `Electricity.tsx` + `src/index.css` | Visual language for the new recommendation card — same accent color, same card recipe, same badge style (§6) |
| `.electricity-btn-primary` / `.electricity-btn-secondary` / `.electricity-ghost-btn` | `src/index.css` | Reference only — the recommendation card renders no button of its own; the existing `Switch Meter` button that already uses `.electricity-btn-primary` is reused unmodified (§10) |
| Existing switch flow: `src/pages/ElectricitySwitchMeter.tsx`, route `/electricity/switch`, and its trigger button in `Electricity.tsx`'s action row | Unchanged | The one existing `Switch Meter` button is reused as-is; the recommendation card adds no button of its own (§10) |
| `hasFeature("electricity_tracker")` from `AuthContext` | `src/App.tsx` (route gate), `src/pages/Dashboard.tsx` (tile gate) | Already gates everything this feature's UI lives inside — no new flag, no new gate (§13 of `backend-spec.md` confirms same flag) |
| `DashboardCard` electricity tile | `src/pages/Dashboard.tsx` | Deliberately **not** modified — see §5 for why |
| Push subscription registration | `src/services/pushApi.ts` | Unchanged — this feature rides the existing subscription, no new opt-in flow |
| Service worker `push`/`notificationclick` handlers | `public/push-sw.js` | Baseline behavior reused as-is; §12 proposes an optional, backward-compatible extension for deep-linking |

No new page, no new route, no new component library, no new CSS framework, no new state-management dependency. Everything is additive to files that already exist for the electricity module.

---

## 3. Required Backend API Contract (proposed extension — see §1)

Extend the existing endpoint's response shape:

```
GET /api/v1/electricity/insights   (unchanged path, unchanged auth — Bearer JWT, same as every other electricity call)

200 OK
{
  "meters": [ ...unchanged... ],
  "slab_recommendation": SlabRecommendation | null
}
```

`SlabRecommendation` (new object, all fields are values `backend-spec.md`'s calculation module already produces internally — see mapping column):

```jsonc
{
  "active_meter_id": "uuid",
  "active_meter_label": "string",              // Meter.label, for display without a second lookup
  "standby_meter_id": "uuid",
  "standby_meter_label": "string",
  "active_cumulative_units": 60.0,               // backend-spec §5/§9 — compute_cumulative(active)
  "active_next_slab_min": 100.0,                 // backend-spec §8 — _next_slab_min(active bracket)
  "active_operational_threshold": 98.0,          // backend-spec §8 — next_slab_min - SLAB_SAFETY_BUFFER_UNITS
  "standby_cumulative_units": 0.0,               // backend-spec §9 — compute_cumulative(standby)
  "standby_next_slab_min": 100.0,
  "standby_operational_threshold": 98.0,
  "recommended_switch_date": "2026-08-26",       // backend-spec §11 — projected_operational_threshold_date, ISO date
  "explanation": "string"                        // new, backend-generated sentence — see §9
}
```

`slab_recommendation` is `null` whenever `backend-spec.md`'s `recommend_switch` (its §10) evaluates to `false` for the requesting user — i.e., exactly the same condition that gates whether a push notification would be sent, minus the push-specific dedup/cooldown bookkeeping (§14 below explains why dedup state must **not** gate this read path).

**Why reuse `/insights` instead of a new endpoint:** `get_insights()` (`electricity_insights_service.py`) already resolves `accessible_meter_ids`, `resolve_active_meter_id`, and per-meter `compute_cumulative`/`bracket_for`/`_next_slab_min` for the exact same user, in the exact same request. Computing `slab_recommendation` is additive work in that same function using data it (or its sibling calculation module) already has in hand — not a second database round trip's worth of new queries wired to a second frontend fetch.

**No new frontend HTTP call.** `getInsights()` (`electricityApi.ts:140`) is called unchanged; only its TypeScript return type gains the new field (§4).

---

## 4. TypeScript Types

Additive changes to `src/services/electricityApi.ts` (no existing interface is removed or renamed):

```ts
export interface SlabRecommendation {
  active_meter_id: string;
  active_meter_label: string;
  standby_meter_id: string;
  standby_meter_label: string;
  active_cumulative_units: number;
  active_next_slab_min: number;
  active_operational_threshold: number;
  standby_cumulative_units: number;
  standby_next_slab_min: number | null;
  standby_operational_threshold: number | null;
  recommended_switch_date: string; // ISO date, e.g. "2026-08-26"
  explanation: string;
}

export interface InsightsResponse {
  meters: InsightsMeter[];
  slab_recommendation: SlabRecommendation | null; // new field
}
```

`standby_next_slab_min`/`standby_operational_threshold` are typed nullable to match `_next_slab_min`'s existing `Optional[float]` return in the backend (the standby meter could already be in its open-ended top slab) — mirroring how `InsightsMeter.next_slab_min` is already `number | null` for the identical reason.

No new function is added to `electricityApi.ts` — `getInsights()`'s existing signature (`(): Promise<InsightsResponse>`) is unchanged; only the shape it resolves to grows one field.

**Verified against the actual file** (`src/services/electricityApi.ts`, read directly for this revision): the existing `InsightsMeter`/`SlabBracket`/`Reading` field names above (`cumulative_units`, `current_bracket`, `next_slab_min`, `status`, `nudge_text`, `last_reading`, `last_billed_reading`, etc.) match the current source exactly, and `getInsights()` is confirmed to be the sole caller of `GET /api/v1/electricity/insights` in the codebase (no other component fetches this endpoint independently), so extending its one response type is sufficient — no second call site needs updating.

---

## 5. Where the Smart Switch Recommendation Appears in the UI

**One place: a new card at the top of the existing `/electricity` page (`Electricity.tsx`), above the per-meter cards.** No new page, no new route.

This is a deliberate, minimal-footprint placement, for two reasons:

1. **Feature-spec's own scope is push-notification-first.** The push notification (title/body, fixed copy per feature-spec §21) is the primary attention-getting surface; the in-app card is the "read more" destination for a user who already has the app open or tapped the notification (§12).
2. **The Dashboard's existing Electricity tile is deliberately left unchanged.** `Dashboard.tsx`'s `DashboardCard` for electricity currently shows one line (`"{active meter label} — {cumulative_units}u"`, or `"No meters yet"`) and is loaded independently of the Electricity page's own fetch. Adding a recommendation badge there would mean either (a) a second, separate fetch of `slab_recommendation` on a screen that doesn't otherwise need per-meter detail, or (b) growing the Dashboard's lightweight summary logic to understand a second data shape. Given the feature is already push-driven, a Dashboard badge is a nice-to-have, not a requirement of any acceptance criterion — this spec intentionally does not add one, to keep the footprint minimal. If product wants a Dashboard indicator later, it's a small additive follow-up (`hasElectricity && electricitySummary?.hasRecommendation`-style boolean), not a redesign.

3. **The existing per-meter cards are not redesigned, touched, or given new props.** `Electricity.tsx`'s `meters.map((meter) => <div className="electricity-meter-card">...)` block — the header/badge row, the odometer, the last-reading/last-billed-reading meta lines, the slab progress bar, and the `nudge_text` callout — is unchanged, byte-for-byte, by this feature. The recommendation card is a new, separate sibling element inserted before that block, not a modification to it. Nothing about a meter's own card changes depending on whether a recommendation exists.

Within `Electricity.tsx`, the new card renders conditionally, immediately after the `<h2>⚡ Electricity</h2>` heading and before the `meters.map(...)` loop, using the same `!loading && !error` branch the rest of the page's content already lives in — i.e., no separate loading/error state (§13, §14).

---

## 6. Recommendation Card Layout and Content

New card, distinct from `.electricity-meter-card` (so it's visually distinguishable as a callout rather than a third "meter"), but built from the same visual vocabulary — same border-radius/shadow/padding recipe, `var(--electricity-copper)` accent, same badge component:

```
┌─────────────────────────────────────────────┐
│ ⚡ Consider switching meters                 │
│                                               │
│  Active: Old Meter            Standby: New Meter
│  60 units                     0 units
│  limit ~98 (slab at 100)      limit ~98 (slab at 100)
│                                               │
│  Your active meter is projected to reach     │
│  its slab limit around 2026-08-26. Switching │
│  to New Meter may help keep usage in a       │
│  lower slab.                                 │
│                                               │
│  Recommended by 2026-08-26                   │
└─────────────────────────────────────────────┘
        (meter cards, then the existing
         Log Reading / Switch Meter action
         row, unchanged, follow below)
```

Concretely, JSX shape (illustrative, not final markup):

```tsx
{recommendation && (
  <div className="electricity-recommendation-card">
    <h3>⚡ Consider switching meters</h3>

    <div className="electricity-recommendation-compare">
      <div>
        <span className="gym-badge electricity-badge-active">Active</span>
        <p className="electricity-recommendation-meter-label">{recommendation.active_meter_label}</p>
        <p className="electricity-recommendation-units">{recommendation.active_cumulative_units} units</p>
        <p className="dash-muted">
          limit ~{recommendation.active_operational_threshold} (slab at {recommendation.active_next_slab_min})
        </p>
      </div>
      <div>
        <span className="gym-badge electricity-badge-standby">Standby</span>
        <p className="electricity-recommendation-meter-label">{recommendation.standby_meter_label}</p>
        <p className="electricity-recommendation-units">{recommendation.standby_cumulative_units} units</p>
        {recommendation.standby_operational_threshold != null && (
          <p className="dash-muted">
            limit ~{recommendation.standby_operational_threshold} (slab at {recommendation.standby_next_slab_min})
          </p>
        )}
      </div>
    </div>

    <p className="electricity-nudge">{recommendation.explanation}</p>

    <p className="electricity-recommendation-date">
      Recommended by {recommendation.recommended_switch_date}
    </p>
  </div>
)}
```

Deliberately **no `<Link>`/button inside this card** — see §10 for why the existing action-row's "Switch Meter" button is reused as the single action surface instead of adding a second one here.

New CSS classes needed (`electricity-recommendation-card`, `-compare`, `-meter-label`, `-units`, `-date`) follow the same recipe already documented for `.electricity-meter-card` in `src/index.css` (card background/border/shadow/padding via existing CSS custom properties) — no new design tokens, no new color.

No monetary figure, no currency symbol, and no guarantee-of-savings language appears anywhere on this card, per feature-spec §21/§29 and AC29 — the explanation string is backend-generated (§9) precisely so this constraint is enforced in one place (the backend), not re-implemented in every place that might render it.

---

## 7. Active and Standby Meter Information Displayed

Per meter (both active and standby), shown side-by-side in the compare row:

- Role badge — reuses `.gym-badge.electricity-badge-active` / `.electricity-badge-standby`, the **exact same classes** `Electricity.tsx` already uses for the per-meter cards below, so a user sees the identical visual vocabulary for "active"/"standby" in both places.
- Meter label (`active_meter_label`/`standby_meter_label` — plain text, no truncation logic beyond what CSS already handles elsewhere).
- Current cumulative units (`active_cumulative_units`/`standby_cumulative_units`) — same unit, same "units" wording as the existing odometer (`Electricity.tsx`'s `formatOdometer`+"units consumed" label), though the recommendation card does **not** reuse the padded-odometer digit styling (that's specific to the primary per-meter card's large display; this is a compact comparison row).

The card does not re-fetch or re-derive which meter is active/standby — it trusts `slab_recommendation.active_meter_id`/`standby_meter_id` exactly as returned, the same way the rest of the page trusts `InsightsMeter.status`.

---

## 8. Current Units and Slab Threshold Presentation

**No hardcoded `100`, anywhere in this feature's frontend code** — every number on the card (`active_cumulative_units`, `active_next_slab_min`, `active_operational_threshold`, and the standby equivalents) is a value read directly from the API response. This satisfies the explicit product rule ("Do not hard-code a 100-unit threshold... Use the slab data returned by the backend").

**Both the raw slab boundary and the safety-buffered threshold are shown together** (`limit ~98 (slab at 100)`), rather than showing only one or the other:

- Showing only `98` (the buffered `operational_threshold`) without also showing `100` would silently disagree with the meter card just below it on the same page, which shows the raw `next_slab_min` (100) via its own slab bar — a user comparing the two would see two different "next slab" numbers with no explanation.
- Showing only `100` would drop the entire point of the safety buffer (backend-spec §8/§11).

Displaying both, with the buffered value labeled "limit" and the raw value labeled "slab at," makes the safety buffer visible (currently 2 units, per `backend-spec.md` §8/§22's `SLAB_SAFETY_BUFFER_UNITS`) without the frontend ever knowing or computing that number itself. **The literal digits `100` and `2` do not appear anywhere in this feature's frontend source** — not as a threshold constant, not as a fallback default, not as a display-formatting magic number. `active_operational_threshold` (already `next_slab_min - SLAB_SAFETY_BUFFER_UNITS`, computed backend-side) and `active_next_slab_min` are both opaque numbers read from the response and displayed as-is; the frontend never subtracts, adds, or otherwise derives one from the other. This is the concrete mechanism by which "the 2-unit safety buffer is backend business logic; the frontend displays the resulting threshold" and "do not hard-code a 100-unit threshold" are both satisfied by construction rather than by convention.

---

## 9. Human-Readable Explanation of Why Switching Is Recommended

**Backend-generated, not frontend-templated.** `slab_recommendation.explanation` is a complete, ready-to-render sentence — the same architectural pattern as `InsightsMeter.nudge_text` (`electricity_insights_service.py`'s `_nudge_text` function), which today already generates sentences like `"98 of 100 units used — close to the next slab, consider switching soon"` server-side for the frontend to render verbatim.

Rendered with the **exact same CSS treatment** as `nudge_text` — the `.electricity-nudge` class (soft copper-tinted callout, `Electricity.tsx`'s existing `{meter.nudge_text && <p className="electricity-nudge">{meter.nudge_text}</p>}` pattern) — so a user already familiar with that visual language on the meter cards recognizes the recommendation card's explanation as the same kind of "here's what this means" text, not a new UI idiom to learn.

The frontend performs **zero string composition** for this text — no `${...}` template combining raw numbers into a sentence in React. This is deliberate: composing the explanation client-side would mean the wording (and the constraint that it never mentions currency) lives in two places (backend push copy and frontend template) instead of one, and any future wording change would need two PRs instead of one. Keeping it 100% backend-owned, exactly like `nudge_text`, avoids that split.

(The compact numeric labels in §8 — "limit ~98 (slab at 100)" — are not prose composition; they're the same kind of raw-value-labeling `Electricity.tsx` already does today for `Slab {min}–{max}` / `Next at {next_slab_min}`, not a sentence generator.)

---

## 10. Switch Meter CTA and Connection to Existing Switch Functionality

**No new button. The recommendation card renders no CTA of its own.** The existing action row's `Switch Meter` button — `{meters.length === MAX_METERS && <Link to="/electricity/switch" className="electricity-btn-primary">Switch Meter</Link>}`, already present in `Electricity.tsx` today, completely unmodified — is the single action surface for acting on a recommendation, exactly as it's the single action surface for switching meters today for any other reason.

This is a deliberate change from an earlier draft of this spec, which put a second `<Link to="/electricity/switch">` inside the recommendation card. On this consistency pass that was reconsidered: rendering the same interaction twice on one page (once inside the card, once in the action row) is a duplicate button, not a reuse of the existing one, even though both instances would point at the identical route/component. The instruction to prefer reuse "unless the existing implementation makes that impossible" applies squarely here — it is **not** impossible to rely on the existing button:

- A `slab_recommendation` is only ever non-null when the user has exactly two accessible meters (feature-spec §4/AC1, enforced backend-side) — which is exactly the condition (`meters.length === MAX_METERS`) that already, unconditionally, renders the existing `Switch Meter` button today. Whenever the card can appear, the existing button is already on the page. There is no case where a recommendation exists but the existing button is hidden.
- `ElectricitySwitchMeter.tsx` needs **zero changes** either way — it already derives `outgoing = meters.find(m => m.status === "active")` / `incoming = meters.find(m => m.status === "standby")` itself on mount, so it doesn't matter which button (there's only one) the user tapped to get there.

**Trade-off, stated plainly:** the recommendation card sits above the per-meter cards, while the action row sits below them (`Electricity.tsx`'s existing element order: heading → recommendation card → meter cards → action row). A user reading the recommendation has to scroll past both meter cards to find the button. This is the accepted cost of not touching existing layout/markup and not introducing a duplicate control.

**Optional follow-up, not part of this spec's V1, flagged for product to consider separately** (same treatment as the push-deep-link question in §12): if tighter CTA/context pairing is wanted later, the existing action row's condition could be narrowed to `meters.length === MAX_METERS && !recommendation` and the identical `<Link>` element moved into the recommendation card in that case — i.e., the button *relocates*, never duplicates. That is a one-line conditional change to `Electricity.tsx`'s existing action row, not a redesign, but it is still a touch to existing code this spec does not ask for by default.

---

## 11. UI Behavior When No Recommendation Exists

`slab_recommendation === null` → **the card section does not render at all.** No placeholder, no "you're all set" filler card, no empty-state illustration.

This matches the existing precedent set by `nudge_text` (`{meter.nudge_text && <p className="electricity-nudge">{meter.nudge_text}</p>}`) and by the meter card's own slab-bracket block (`{meter.current_bracket && (...)}`) — both already render nothing rather than a placeholder when the underlying condition is absent. A recommendation is inherently an exceptional callout, not a persistent page section that always needs *some* content — introducing a "no action needed right now" filler card would be new UI surface the feature spec never asks for, and would add a permanent element to a page that's otherwise data-first.

The page's normal content (meter cards, actions row, setup form) renders exactly as it does today, unaffected by whether a recommendation exists.

---

## 12. Push-Notification Tap Behavior and Navigation

**Baseline (works today, zero changes required):** `public/push-sw.js`'s `notificationclick` handler focuses an existing app window/tab if one is open, or opens the app at `/` if none is open. It does not currently read any payload field to decide *where* to navigate — every notification type (skincare, water, and this new one) behaves identically: open/focus the app root.

Given there is **no bottom-navigation tab for Electricity** (`BottomNavigation.tsx` only has Home/Gym/Skin/Water/Me), a user who taps this notification with the baseline behavior lands on the Dashboard and must additionally tap the Electricity tile to reach the recommendation card. This is a real but pre-existing UX limitation (it already affects nothing today since no other notification type needs a deep link either), not something this feature spec is required to fix.

**Proposed optional improvement** (flagged, like §1, as a cross-cutting change beyond this feature's own code — touches shared infrastructure used by every notification type, and requires a corresponding backend payload change beyond `backend-spec.md`'s current `send_to_user(db, user_id, title, body)` signature):

1. Backend: `PushService.send_to_user` gains an optional fourth parameter, e.g. `data: dict | None = None`, included in the JSON payload only when provided (`json.dumps({"title": title, "body": body, **({"data": data} if data else {})})`) — existing call sites (`dispatch_due`, `dispatch_water_due`) pass nothing and are unaffected; `dispatch_meter_slab_recommendation` would pass `data={"url": "/electricity"}`.
2. Frontend: `push-sw.js`'s `push` handler reads `payload.data` and passes it through to `showNotification(title, {body, icon, badge, data: payload.data})`; `notificationclick` reads `event.notification.data?.url ?? "/"` and calls `clients.openWindow(url)` (or focuses+navigates an existing client to that URL, falling back to root if navigation isn't possible on an already-open client).

This is explicitly **optional for V1** — the feature is fully usable without it (the recommendation card is reachable via Dashboard → Electricity regardless). It's documented here so the decision to defer it is a conscious one, not an oversight, and so a future implementer has the exact shape ready if product wants it. If adopted, it should be proposed as a small addendum to `backend-spec.md` §13 (which currently states the payload is title/body only "matching every other existing push type") at the same time, since it changes a statement made there.

---

## 13. Loading State

**No new loading state.** The recommendation card is fetched as part of the same `getInsights()` call the rest of `Electricity.tsx` already makes; while that call is in flight, the page's existing `loading` branch (two `<SkeletonCard lines={4} />`) covers the whole page, recommendation included. There is no separate spinner or skeleton specifically for the recommendation card, and none is needed — splitting it into a second, independently-loading fetch would contradict §3's whole rationale (one round trip, not two).

---

## 14. Error State

**No new error state.** If `getInsights()` rejects, the existing `!loading && error` branch (`.status-error` card + `Retry` button, calling the existing `retryLoad`) covers the whole page. A failure to load the recommendation is indistinguishable from a failure to load anything else on the page, which is the correct behavior — there is no scenario where meters load successfully but the recommendation half of the same response object fails independently (it's one JSON payload, one HTTP response).

---

## 15. Stale Recommendation Handling

The recommendation is **never cached across page loads or persisted to `localStorage`.** Every mount of `Electricity.tsx` calls `getInsights()` fresh (its existing `useEffect([reloadKey])`), which re-invokes the backend's evaluation from scratch (backend-spec §10/§19: "re-evaluate the current state on every dispatch" — the read path this spec proposes uses the identical calculation, so it re-evaluates on every *read* too, not just on every dispatch). This means:

- A recommendation shown yesterday is never displayed today without being freshly recomputed — there is no version of "stale data silently shown" possible, because nothing is retained between mounts.
- If the user already switched meters (via the existing switch flow) since the last time they viewed the page, the next fetch reflects the new active/standby pair automatically — no manual invalidation needed (§16).
- If the opportunity has resolved on its own (e.g., a new bill was logged, resetting the billing anchor), the next fetch simply returns `slab_recommendation: null`, and the card silently stops appearing (§11) — there is no separate "this recommendation has expired" message, because from the frontend's perspective there was never a distinct "expired" state, only "currently recommended" or "not currently recommended," re-evaluated fresh every time.

The one thing this spec deliberately does **not** add: a polling/auto-refresh interval to keep an already-open tab's recommendation card up to date in the background. No page in this app currently polls (every fetch is mount-triggered or action-triggered — confirmed across `Electricity.tsx`, `Water.tsx`, `Dashboard.tsx`), so introducing one for this feature alone would be a new pattern the app doesn't otherwise have, for a feature whose primary attention-getting mechanism is already a push notification, not a live-updating dashboard. A user who wants a refreshed view can navigate away and back, or use the existing `Retry` affordance.

---

## 16. Behavior After the User Switches Meters

No changes to `ElectricitySwitchMeter.tsx`. Its existing post-switch flow already ends with a `Link to="/electricity"` ("⚡ Back to Electricity") — tapping it is a normal client-side navigation to `Electricity.tsx`, which unconditionally re-runs its `useEffect` on mount and calls `getInsights()` fresh.

Because the backend recomputes `slab_recommendation` from the current `resolve_active_meter_id`/`Meter.last_billed_reading_id` state on every call (§3, §15), the very next load of `/electricity` after a switch reflects the new pair automatically:

- If the newly-active meter (the former standby) has no billing anchor of its own yet (a common outcome right after a switch — `backend-spec.md` §19's "No billed reading" edge case, since the incoming reading is not marked `is_billed_reading` unless explicitly checked during the switch), `slab_recommendation` is `null` and the card disappears entirely until that meter has its own bill logged. This is expected and requires no special-case handling in the frontend — it's the same "no recommendation" path as §11, just reached via a different backend condition.
- If a recommendation is still applicable (e.g., the user switched for an unrelated reason and the new active meter is itself already close to a threshold), the card reappears with the new meter now in the "active" slot — again, no frontend logic needed beyond rendering whatever the response contains.

---

## 17. Responsive/Mobile Behavior

The entire app is mobile-first with a single fixed container width pattern (`max-width: 500px; margin: 0 auto`, see `.electricity-container`, `.water-container`) and no distinct desktop layout — this feature follows the same convention with no new breakpoints.

Within the card, the active/standby compare row (§6) is a simple two-column flex/grid at the container's full width (500px max, so each column is roughly 240px on the narrowest supported phone widths) — this comfortably fits a meter label, a unit count, and one muted line per column without wrapping awkwardly on any viewport this app already targets (confirmed no existing electricity UI needs a narrower fallback layout, e.g. the existing meter card's own head row — label + badge — already works at this width). If a future design pass finds label overflow on unusually long meter labels, that's a CSS text-truncation fix (`text-overflow: ellipsis`), not a structural layout concern for this spec.

No responsive concern applies to a `Switch Meter` button specifically, since this feature adds none — the pre-existing action-row button (`.electricity-btn-primary`) is already full-width-capable at this container size and is left entirely as-is.

---

## 18. Accessibility Requirements

Matching the app's existing conventions (paired labels on inputs, `aria-hidden` on decorative skeletons, `aria-label` on icon-only controls, semantic heading levels):

- The recommendation card heading (`⚡ Consider switching meters`) uses `<h3>`, matching the heading level `Electricity.tsx`'s own meter cards use for their `<h3>{meter.label}</h3>` — keeps the page's heading hierarchy consistent (`<h2>⚡ Electricity</h2>` → `<h3>` per card/section) rather than introducing a `<h4>` or skipping a level.
- No icon-only interactive elements are introduced — the emoji in the heading (`⚡`) is decorative and adjacent to descriptive text, not a standalone control, so it needs no `aria-label` (consistent with how the page's `<h2>⚡ Electricity</h2>` and per-meter headings already treat emoji as decoration, not as the accessible name).
- No new interactive control is introduced by the recommendation card at all (§10), so there is no new accessible-name concern to evaluate for a CTA — the pre-existing `Switch Meter` link's accessible name (its own visible text) is unaffected, since it isn't touched.
- The active/standby distinction is conveyed by **text** ("Active"/"Standby" badge labels), not by color alone — reusing `.electricity-badge-active`/`-standby`, which already pair a color with a text label rather than relying on hue alone, satisfying the same non-color-only requirement the existing badges already meet.
- The explanation text (§9) is a plain `<p>`, read naturally by screen readers in document order along with the rest of the card — no `aria-live` region is needed, since the card's appearance/disappearance happens on full-page load (§13-§15), not as a dynamic in-place update a screen reader user could otherwise miss mid-session.

---

## 19. Frontend Automated Tests

**This repository currently has zero frontend automated tests and no test runner configured** — `package.json` lists no `vitest`/`jest`/`@testing-library/react` (or any test script beyond `lint`/`build`), and no `*.test.*` files exist anywhere in `src/`. This is a pre-existing gap, not something introduced by this feature, and bootstrapping a test framework is a repository-wide infrastructure decision that is out of scope for one feature spec to silently impose (it would also affect every other page's testability, not just this one).

Given that, this section is split into two parts:

### 19.1 Forward-looking automated test cases (once a test framework exists)

Written against the standard Vite pairing (Vitest + React Testing Library) as the most likely eventual choice, since it requires no build-tool changes beyond adding dev dependencies — but the specific runner is an infra decision for whoever bootstraps it, not fixed by this spec.

1. `slab_recommendation: null` → recommendation card does not render; rest of the page renders normally (§11).
2. `slab_recommendation` present → card renders active/standby labels, units, thresholds, explanation text, and recommended date exactly from the response fields, with no client-side recomputation (assert no arithmetic performed on the numbers beyond direct interpolation).
3. Card never renders a `$`/currency-symbol character or the substring "sav" (case-insensitive) regardless of mocked response content — a regression guard mirroring the backend's own AC29 test, on the frontend rendering layer.
4. Exactly one `Switch Meter` link (`href="/electricity/switch"`) is present on the page when a recommendation is active — a regression guard against the card ever growing its own duplicate button (§10). The recommendation card itself renders no `<a>`/`<Link>` element.
5. `getInsights()` rejecting → the page's existing single error branch renders (`.status-error` + Retry) and no recommendation-specific error UI appears.
6. `getInsights()` pending → the page's existing loading branch renders (`SkeletonCard`s) and no recommendation-specific loading UI appears.
7. After a simulated switch-and-return-navigation, a second `getInsights()` mock response with different active/standby ids and/or `slab_recommendation: null` is reflected on next render with no stale data from the first response retained.
8. Snapshot/visual check that no hardcoded `100` (or any other literal slab number) appears in the component source for this feature — a lint-shaped regression guard for the "no hardcoded threshold" product rule, since a unit test can't fully verify the absence of a magic number but a source-grep-based check can be added to CI.

### 19.2 Practical fallback until a test framework exists

Manual QA checklist, mapped to the same scenarios, to be run against a local dev server pointed at a backend with the proposed `slab_recommendation` field seeded via direct DB manipulation or a temporary mock:

- Load `/electricity` with a seeded active recommendation → verify card content matches §6-§9.
- Load `/electricity` with `slab_recommendation: null` → verify no card, rest of page normal.
- Trigger the existing switch flow → verify the card updates (or disappears) after returning to `/electricity`.
- Throttle network to simulate the existing loading/error states → verify no separate recommendation-specific spinner/error appears.

---

## 20. Frontend Acceptance Criteria Mapped to the Feature Spec

Only feature-spec acceptance criteria with a frontend-visible surface are listed (most of AC1-AC29 are backend-only and already covered by `backend-spec.md` §21; this table covers the subset the frontend is responsible for rendering correctly).

| AC | Feature-spec requirement | Frontend spec section(s) |
|---|---|---|
| AC8 | Uses configured slabs, no hardcoded 100 | §8 — every number rendered from the API, no literal `100` anywhere in this feature's code |
| AC9 | Safety buffer reflected (98 for a 100 boundary, buffer 2) | §8 — both `active_operational_threshold` and `active_next_slab_min` shown, buffer never computed client-side |
| AC17 | Both meters near threshold → no blind switch recommendation | §11 — `slab_recommendation: null` in this case (per backend-spec §10), card doesn't render; frontend adds no independent judgment |
| AC18 | Recommended switch date | §6, §9 — `recommended_switch_date` rendered as-is (ISO date, matching the existing convention of showing reading dates unformatted elsewhere on this page) |
| AC19/AC20/AC21 | Owner/shared-user notified, independently | Not a frontend concern beyond §12 (notification tap) — recipient resolution and dedup are entirely backend-side (backend-spec §12/§14); the frontend just renders whatever `/insights` returns for whichever user is logged in |
| AC23 | Re-evaluate after a switch | §16 — next page load reflects the new active/standby pair with no client-side state carried over |
| AC24 | New billing anchor → new lifecycle | §15 — next fetch simply reflects current backend state; frontend has no lifecycle concept of its own |
| AC28 | Feature-flag gated | §2 — reuses the existing `hasFeature("electricity_tracker")` gate already wrapping the entire `/electricity` route; no new flag |
| AC29 | No monetary claim | §6, §9 — explanation is backend-owned text (never client-templated), and §19.1 proposes an automated regression guard against currency-shaped strings appearing in the rendered card |

Every other acceptance criterion (AC1-AC7, AC10-AC16, AC22, AC25-AC27) governs backend evaluation/dispatch/dedup/auth logic with no distinct frontend rendering behavior beyond "render whatever the backend decided" — already covered by the general statement that this feature performs no independent computation, judgment, or caching of its own (§3, §11, §15).

---

## 21. Consistency Check Against the Backend Spec

- **No algorithm duplication**: confirmed throughout — every numeric/date field the card shows is read directly from the proposed `slab_recommendation` object; the frontend never computes a rate, a threshold, a buffer, or a date of its own. (Satisfies the explicit product rule and `backend-spec.md`'s Implementation Principle #3 analogue.)
- **Same feature flag**: confirmed (§2) — no new flag introduced, matching `backend-spec.md` §18's explicit "same flag, no new `feature_key` value."
- **Same switch mechanism, no duplicate control**: confirmed (§10) — the recommendation card adds no button of its own; the single pre-existing `Switch Meter` link/route/component is reused unmodified. `backend-spec.md`'s Out of Scope list ("Changes to the existing meter-switch UI... Changes to `create_switch_event`") is respected by construction, since nothing here touches that page, that button, or that backend function.
- **No monetary claims**: confirmed (§6, §9, §20) — reinforced by treating the explanation as opaque backend-owned text rather than a frontend template that could accidentally grow a currency figure later.
- **One open dependency**: §1/§3 — this is the one place this spec is not fully "satisfied by what already exists" in `backend-spec.md`, and it's called out explicitly rather than assumed. Everything else in this document is buildable against `backend-spec.md` and the current frontend codebase exactly as they stand today.
