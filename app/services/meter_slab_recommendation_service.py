"""Pure calculation module for the smart meter-slab-switch recommendation:
billing-period estimation, consumption-rate/projection math, slab/buffer
math, switch-decision logic, recommended-switch-date math, and
explanation-text generation.

No DB writes, no push calls, no ReminderDispatchLog reads — the two
callers (push_service.dispatch_meter_slab_recommendation and
electricity_insights_service.get_insights) each add exactly one of those on
top of evaluate_switch_recommendation's result; neither re-implements any
part of the decision itself.
"""

from dataclasses import dataclass
from datetime import date, timedelta
from math import floor
from typing import Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.electricity import Meter, MeterReading, SlabThreshold
from app.services.electricity_insights_service import (
    _next_slab_min,
    accessible_meter_ids,
    bracket_for,
    compute_cumulative,
    expected_billing_period_end,
    recent_rate_per_day,
    resolve_active_meter_id,
)


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


def evaluate_switch_recommendation(
    db: Session, user_id: UUID, today: date
) -> Optional[SwitchRecommendation]:
    """The single entrypoint both the dispatch path and the read path call.
    Returns a fully-populated recommendation or None — never a partial
    result. See feature-spec.md and backend-spec.md for the full rules."""
    meter_ids = accessible_meter_ids(db, user_id)
    if len(meter_ids) != 2:
        return None

    active_meter_id = resolve_active_meter_id(db, user_id)
    if active_meter_id is None or active_meter_id not in meter_ids:
        return None

    meters_by_id = {m.id: m for m in db.query(Meter).filter(Meter.id.in_(meter_ids)).all()}
    active_meter = meters_by_id.get(active_meter_id)
    standby_meter_id = next((mid for mid in meter_ids if mid != active_meter_id), None)
    standby_meter = meters_by_id.get(standby_meter_id) if standby_meter_id is not None else None
    if active_meter is None or standby_meter is None:
        return None

    # A missing billing anchor is a hard skip — compute_cumulative's own
    # first-ever-reading fallback must never be mistaken for a real bill.
    if active_meter.last_billed_reading_id is None:
        return None
    anchor = (
        db.query(MeterReading)
        .filter(MeterReading.id == active_meter.last_billed_reading_id)
        .first()
    )
    if anchor is None:
        return None

    elapsed_days = (today - anchor.reading_date).days
    if elapsed_days < settings.meter_slab_min_evaluation_days:
        return None

    cumulative_active, _, _ = compute_cumulative(db, active_meter)
    cumulative_standby, _, _ = compute_cumulative(db, standby_meter)

    slabs_by_meter = {}
    for slab in (
        db.query(SlabThreshold)
        .filter(SlabThreshold.meter_id.in_([active_meter.id, standby_meter.id]))
        .all()
    ):
        slabs_by_meter.setdefault(slab.meter_id, []).append(slab)
    active_slabs = slabs_by_meter.get(active_meter.id, [])
    standby_slabs = slabs_by_meter.get(standby_meter.id, [])

    active_bracket = bracket_for(cumulative_active, active_slabs)
    active_next_min = _next_slab_min(active_bracket, active_slabs)
    standby_bracket = bracket_for(cumulative_standby, standby_slabs)
    standby_next_min = _next_slab_min(standby_bracket, standby_slabs)

    overall_rate = cumulative_active / elapsed_days
    recent_rate = recent_rate_per_day(db, active_meter)
    projection_rate = max(overall_rate, recent_rate) if recent_rate is not None else overall_rate

    if cumulative_active <= 0 or projection_rate <= 0:
        return None

    if active_next_min is None:
        # Already in the open-ended top slab — nothing further to project
        # toward, and switching can't undo consumption already recorded.
        return None

    active_operational_threshold = active_next_min - settings.meter_slab_safety_buffer_units
    standby_operational_threshold = (
        standby_next_min - settings.meter_slab_safety_buffer_units
        if standby_next_min is not None
        else None
    )

    remaining_capacity_active = active_operational_threshold - cumulative_active
    projected_days_to_threshold = remaining_capacity_active / projection_rate
    projected_operational_threshold_date = today + timedelta(days=floor(projected_days_to_threshold))

    billing_period_end = expected_billing_period_end(db, meter_ids, anchor)
    opportunity_exists = projected_operational_threshold_date < billing_period_end
    if not opportunity_exists:
        return None

    remaining_capacity_standby = (
        standby_operational_threshold - cumulative_standby
        if standby_operational_threshold is not None
        else None
    )
    standby_is_meaningful = (
        standby_operational_threshold is not None
        and remaining_capacity_standby > remaining_capacity_active
    )
    if not standby_is_meaningful:
        return None

    recommended_switch_date = projected_operational_threshold_date

    explanation = (
        f"{active_meter.label} is projected to reach its slab limit around "
        f"{recommended_switch_date.isoformat()}. Switching to {standby_meter.label} "
        "may help keep your usage in a lower slab."
    )

    return SwitchRecommendation(
        active_meter_id=active_meter.id,
        active_meter_label=active_meter.label,
        standby_meter_id=standby_meter.id,
        standby_meter_label=standby_meter.label,
        active_cumulative_units=cumulative_active,
        active_next_slab_min=active_next_min,
        active_operational_threshold=active_operational_threshold,
        standby_cumulative_units=cumulative_standby,
        standby_next_slab_min=standby_next_min,
        standby_operational_threshold=standby_operational_threshold,
        recommended_switch_date=recommended_switch_date,
        explanation=explanation,
    )
