"""Cross-entity read logic for the electricity module: which meter is active,
how many units a meter has used since its last bill, which slab bracket
that falls in, and what to tell the user about it. Kept separate from
electricity_service.py's CRUD/writes, same split as gym's workout_service vs
insights_service.
"""

from datetime import date, datetime, timedelta
from statistics import median
from typing import List, Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.timezone import local_today
from app.models.electricity import Meter, MeterReading, MeterShare, MeterSwitchEvent, SlabThreshold
from app.models.user import User

# How close to the next slab boundary (as a fraction of the current
# bracket's width) counts as "approaching" — nudge proactively before that
# point, drop to purely informational once it's been crossed.
APPROACHING_FRACTION = 0.15


def accessible_meter_ids(db: Session, user_id: UUID) -> List[UUID]:
    """Meters this user can see/log on: the ones they own, plus any shared
    with them via MeterShare. Every read/write path that used to filter on
    Meter.user_id == user_id alone should filter on this set instead."""
    owned = db.query(Meter.id).filter(Meter.user_id == user_id)
    shared = db.query(MeterShare.meter_id).filter(MeterShare.shared_with_user_id == user_id)
    return [row.id for row in owned] + [row.meter_id for row in shared]


def shared_emails_by_meter(db: Session, meter_ids: List[UUID]) -> dict:
    """meter_id -> list of emails it's been shared with, for the meters that
    have any shares at all — meters with none just won't be a key."""
    if not meter_ids:
        return {}
    rows = (
        db.query(MeterShare.meter_id, User.email)
        .join(User, User.id == MeterShare.shared_with_user_id)
        .filter(MeterShare.meter_id.in_(meter_ids))
        .all()
    )
    result: dict = {}
    for meter_id, email in rows:
        result.setdefault(meter_id, []).append(email)
    return result


def resolve_active_meter_id(db: Session, user_id: UUID) -> Optional[UUID]:
    """The active meter = incoming_meter_id of the most recent switch event
    among this user's accessible meters, or the first-created accessible
    meter if there's never been a switch. Based on the accessible meter set
    rather than the requesting user's own switch_events.user_id, so a shared
    user sees the same active/standby status as the owner — a switch is a
    property of the meters, not of whoever happened to log it."""
    meter_ids = accessible_meter_ids(db, user_id)
    if not meter_ids:
        return None

    latest_switch = (
        db.query(MeterSwitchEvent)
        .filter(
            MeterSwitchEvent.incoming_meter_id.in_(meter_ids)
            | MeterSwitchEvent.outgoing_meter_id.in_(meter_ids)
        )
        .order_by(MeterSwitchEvent.switched_at.desc())
        .first()
    )
    if latest_switch is not None:
        return latest_switch.incoming_meter_id

    first_meter = (
        db.query(Meter)
        .filter(Meter.id.in_(meter_ids))
        .order_by(Meter.created_at.asc())
        .first()
    )
    return first_meter.id if first_meter is not None else None


def _anchor_and_latest_reading(db: Session, meter: Meter):
    """anchor = the reading cumulative-since-bill is measured from (the last
    reading marked billed, or the meter's very first reading if it's never
    been billed). latest = the meter's most recent reading. Either can be
    None if the meter has no readings yet."""
    latest = (
        db.query(MeterReading)
        .filter(MeterReading.meter_id == meter.id)
        .order_by(MeterReading.reading_date.desc(), MeterReading.created_at.desc())
        .first()
    )

    if meter.last_billed_reading_id is not None:
        anchor = (
            db.query(MeterReading)
            .filter(MeterReading.id == meter.last_billed_reading_id)
            .first()
        )
    else:
        anchor = (
            db.query(MeterReading)
            .filter(MeterReading.meter_id == meter.id)
            .order_by(MeterReading.reading_date.asc(), MeterReading.created_at.asc())
            .first()
        )

    return anchor, latest


def compute_cumulative(db: Session, meter: Meter):
    """Returns (cumulative_units, anchor_reading, latest_reading). Cumulative
    is latest - anchor, not a sum of per-reading deltas — the two are
    equivalent (telescoping sum) but this avoids re-touching every
    intermediate reading."""
    anchor, latest = _anchor_and_latest_reading(db, meter)
    if anchor is None or latest is None:
        return 0.0, anchor, latest
    return float(latest.reading_value) - float(anchor.reading_value), anchor, latest


def recent_rate_per_day(db: Session, meter: Meter) -> Optional[float]:
    """units/day between a meter's two most-recent readings, or None if
    there aren't two, or they share a reading_date (can't divide by zero
    days). Moved here from meter_slab_recommendation_service so both the
    switch-recommendation path and the insights rate fields share one
    implementation instead of two."""
    last_two = (
        db.query(MeterReading)
        .filter(MeterReading.meter_id == meter.id)
        .order_by(MeterReading.reading_date.desc(), MeterReading.created_at.desc())
        .limit(2)
        .all()
    )
    if len(last_two) != 2:
        return None

    latest, previous = last_two
    if latest.reading_date == previous.reading_date:
        return None

    days = (latest.reading_date - previous.reading_date).days
    return (float(latest.reading_value) - float(previous.reading_value)) / days


def expected_billing_period_end(db: Session, meter_ids: List[UUID], anchor: MeterReading) -> date:
    """Estimated end of the current billing period: anchor date + a typical
    billing-period length, derived from the median of historical billed-
    reading intervals pooled across the given meters, or the configured
    default when too little history exists.

    Billed readings sharing a calendar date (e.g. a shared meter's bill
    confirmed by more than one accessible user) represent one billing
    date, not several — intervals are computed from the distinct set of
    dates, never the raw row list, so a duplicate date can never
    manufacture a 0-day interval."""
    distinct_billed_dates = sorted(
        {
            row.reading_date
            for row in db.query(MeterReading)
            .filter(
                MeterReading.meter_id.in_(meter_ids),
                MeterReading.is_billed_reading.is_(True),
            )
            .all()
        }
    )
    intervals = [
        (distinct_billed_dates[i] - distinct_billed_dates[i - 1]).days
        for i in range(1, len(distinct_billed_dates))
    ]

    if len(intervals) >= settings.meter_slab_min_billing_intervals_for_estimate:
        typical_billing_period_days = round(median(intervals))
    else:
        typical_billing_period_days = settings.meter_slab_default_billing_period_days

    return anchor.reading_date + timedelta(days=typical_billing_period_days)


def bracket_for(cumulative: float, slabs: List[SlabThreshold]) -> Optional[SlabThreshold]:
    """The bracket containing `cumulative`. slab_max is exclusive (hitting it
    exactly means you're already in the next slab) — matches the reviewed
    mockup's "Slab 2 at 100" labeling for a 0-100 first bracket."""
    ordered = sorted(slabs, key=lambda s: s.slab_min)
    for slab in ordered:
        if slab.slab_max is None or cumulative < float(slab.slab_max):
            return slab
    return ordered[-1] if ordered else None


def _next_slab_min(bracket: Optional[SlabThreshold], slabs: List[SlabThreshold]) -> Optional[float]:
    if bracket is None or bracket.slab_max is None:
        return None
    ordered = sorted(slabs, key=lambda s: s.slab_min)
    for slab in ordered:
        if slab.slab_min >= float(bracket.slab_max):
            return float(slab.slab_min)
    return float(bracket.slab_max)


def _nudge_text(
    cumulative: float, bracket: Optional[SlabThreshold], next_min: Optional[float], is_active: bool
) -> Optional[str]:
    if bracket is None:
        return None

    if next_min is None:
        return f"{cumulative:g} units used — top slab, no further brackets"

    remaining = next_min - cumulative
    if remaining <= 0:
        # Already past the boundary — switching now wouldn't undo it, so the
        # tone stays informational rather than urging an immediate switch.
        return f"{cumulative:g} units used — already past this slab's limit"

    bracket_width = next_min - float(bracket.slab_min)
    threshold = bracket_width * APPROACHING_FRACTION if bracket_width > 0 else 0
    if remaining <= threshold:
        suffix = "consider switching soon" if is_active else "not currently in use"
        return f"{cumulative:g} of {next_min:g} units used — close to the next slab, {suffix}"

    tone = "comfortably inside" if is_active else "not currently in use"
    return f"{cumulative:g} of {next_min:g} units used — {tone} this slab"


def get_insights(db: Session, user_id: UUID) -> dict:
    # Local import: meter_slab_recommendation_service imports several of this
    # module's own functions, so importing it at module level here would be
    # circular. Deferring it to call time breaks the cycle.
    from app.services.meter_slab_recommendation_service import evaluate_switch_recommendation

    meter_ids = accessible_meter_ids(db, user_id)
    if not meter_ids:
        return {"meters": [], "slab_recommendation": None}

    meters = (
        db.query(Meter)
        .filter(Meter.id.in_(meter_ids))
        .order_by(Meter.created_at.asc())
        .all()
    )

    active_meter_id = resolve_active_meter_id(db, user_id)
    recommendation = evaluate_switch_recommendation(db, user_id, local_today())

    slabs_by_meter = {}
    all_slabs = (
        db.query(SlabThreshold)
        .filter(SlabThreshold.meter_id.in_([m.id for m in meters]))
        .all()
    )
    for slab in all_slabs:
        slabs_by_meter.setdefault(slab.meter_id, []).append(slab)

    shared_by_meter = shared_emails_by_meter(db, meter_ids)

    today = datetime.utcnow().date()
    results = []
    for meter in meters:
        is_active = meter.id == active_meter_id
        cumulative, anchor, latest = compute_cumulative(db, meter)
        slabs = slabs_by_meter.get(meter.id, [])
        bracket = bracket_for(cumulative, slabs)
        next_min = _next_slab_min(bracket, slabs)
        # anchor falls back to the meter's first-ever reading when it's never
        # been billed — that's not an actual bill, so don't label it as one.
        billed_reading = anchor if meter.last_billed_reading_id is not None else None
        is_owner = meter.user_id == user_id

        elapsed_days = (today - anchor.reading_date).days if anchor else None

        # anchor == latest means this meter has only ever had one reading in
        # this billing cycle — there's no second data point to compute a
        # rate from, however much wall-clock time has passed since then.
        has_two_points = anchor is not None and latest is not None and anchor.id != latest.id

        # Rate is based on the SPAN OF ACTUAL READINGS (anchor -> latest),
        # not elapsed time to "today" — so it reflects real historical pace
        # even for a standby meter that hasn't been read since it was
        # switched away from, instead of decaying toward zero the longer
        # it sits untouched. This applies to every meter, active or not.
        rate_span_days = (latest.reading_date - anchor.reading_date).days if has_two_points else None
        daily_rate = cumulative / rate_span_days if (has_two_points and rate_span_days) else None
        recent_rate = recent_rate_per_day(db, meter)

        # Projection is forward-looking ("by your next bill you'll be at
        # X") and only means something for the meter you're actually
        # drawing from right now — a standby meter gets a rate (above) but
        # no projection, since it isn't accumulating further usage toward
        # a future bill.
        billing_end = None
        projected_units = None
        if is_active:
            if daily_rate is not None and recent_rate is not None:
                projection_rate = max(daily_rate, recent_rate)
            else:
                projection_rate = daily_rate if daily_rate is not None else recent_rate

            billing_end = expected_billing_period_end(db, meter_ids, anchor) if anchor else None
            if projection_rate is not None and billing_end is not None:
                days_remaining = max(0, (billing_end - today).days)
                projected_units = cumulative + projection_rate * days_remaining

        results.append(
            {
                "meter_id": meter.id,
                "label": meter.label,
                "meter_number": meter.meter_number,
                "status": "active" if is_active else "standby",
                "is_owner": is_owner,
                # Only the owner sees who else has access — see the matching
                # comment on _meter_response in electricity_service.py.
                "shared_with": shared_by_meter.get(meter.id, []) if is_owner else [],
                "cumulative_units": cumulative,
                "last_reading": latest,
                "last_billed_reading": billed_reading,
                "days_since_bill": elapsed_days,
                "current_bracket": bracket,
                "next_slab_min": next_min,
                "nudge_text": _nudge_text(cumulative, bracket, next_min, is_active),
                "daily_rate": daily_rate,
                "recent_rate": recent_rate,
                "expected_billing_period_end": billing_end,
                "projected_units_at_billing_end": projected_units,
            }
        )

    return {"meters": results, "slab_recommendation": recommendation}