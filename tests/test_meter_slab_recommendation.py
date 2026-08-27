import uuid
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

from app.core.config import Settings, settings
from app.core.security import decode_token
from app.database.session import SessionLocal
from app.models.electricity import Meter, MeterReading, MeterShare, MeterSwitchEvent
from app.models.feature_flag import FeatureFlag
from app.models.push_subscription import PushSubscription
from app.models.reminder_dispatch_log import ReminderDispatchLog
from app.services.meter_slab_recommendation_service import evaluate_switch_recommendation
from app.services.push_service import PushService

FEATURE_KEY = "electricity_tracker"

# Fixed "today" used by every test that calls evaluate_switch_recommendation
# directly with an explicit `today` argument (no monkeypatching needed there).
TODAY = date(2026, 6, 15)


@pytest.fixture
def db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


# ----- Shared test helpers -----

def _register(client, email):
    response = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "supersecret123"},
    )
    token = response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}, uuid.UUID(decode_token(token))


def _enable_feature(db, user_id, enabled=True):
    db.add(FeatureFlag(user_id=user_id, feature_key=FEATURE_KEY, enabled=enabled))
    db.commit()


def _meter(db, user_id, label, slabs=(("0", 100), (100, None))):
    meter = Meter(user_id=user_id, label=label)
    db.add(meter)
    db.flush()
    for slab_min, slab_max in slabs:
        db.add(_slab(meter.id, slab_min, slab_max))
    db.commit()
    db.refresh(meter)
    return meter


def _slab(meter_id, slab_min, slab_max):
    from app.models.electricity import SlabThreshold

    return SlabThreshold(meter_id=meter_id, slab_min=float(slab_min), slab_max=slab_max)


def _reading(db, meter_id, reading_date, value, is_billed=False, update_anchor=True):
    """update_anchor=False lets a caller add a historical is_billed_reading
    row (for billing-period-interval estimation) without repointing the
    meter's *current* anchor away from the reading that's meant to stay
    the anchor."""
    reading = MeterReading(
        meter_id=meter_id,
        reading_value=value,
        reading_date=reading_date,
        entry_method="manual",
        is_billed_reading=is_billed,
    )
    db.add(reading)
    db.flush()
    if is_billed and update_anchor:
        db.query(Meter).filter(Meter.id == meter_id).update({"last_billed_reading_id": reading.id})
        db.flush()
    db.commit()
    db.refresh(reading)
    return reading


def _share(db, meter_id, shared_with_user_id):
    db.add(MeterShare(meter_id=meter_id, shared_with_user_id=shared_with_user_id))
    db.commit()


def _seed(
    db,
    user_id,
    anchor_date,
    today,
    active_units=60,
    standby_units=0,
    active_slabs=(("0", 100), (100, None)),
    standby_slabs=None,
    active_billed=True,
    active_label="Active Meter",
    standby_label="Standby Meter",
):
    """The default happy-path scenario, matching feature-spec.md's own worked
    example (A=60 active, B=0 standby, boundary 100, buffer 2 -> recommend).
    active_meter is created first so resolve_active_meter_id treats it as
    active by default (no switch event needed)."""
    standby_slabs = standby_slabs if standby_slabs is not None else active_slabs
    active_meter = _meter(db, user_id, active_label, active_slabs)
    standby_meter = _meter(db, user_id, standby_label, standby_slabs)

    _reading(db, active_meter.id, anchor_date, 1000, is_billed=active_billed)
    _reading(db, active_meter.id, today, 1000 + active_units)

    _reading(db, standby_meter.id, anchor_date, 0)
    _reading(db, standby_meter.id, today, standby_units)

    db.refresh(active_meter)
    return active_meter, standby_meter


def _freeze(monkeypatch, day, tz=None):
    """Freeze app.core.timezone.local_now (and therefore local_today) to a
    fixed calendar date, following tests/test_gym.py's precedent."""
    if tz is not None:
        fixed_dt = datetime(day.year, day.month, day.day, 12, 0, tzinfo=ZoneInfo(tz))
    else:
        fixed_dt = datetime(day.year, day.month, day.day, 12, 0)
    monkeypatch.setattr("app.core.timezone.local_now", lambda: fixed_dt)


def _add_subscription(db, user_id):
    sub = PushSubscription(
        user_id=user_id,
        endpoint=f"https://example.com/{uuid.uuid4()}",
        p256dh="fake-p256dh",
        auth="fake-auth",
    )
    db.add(sub)
    db.commit()
    return sub


def _mock_webpush_success(monkeypatch):
    monkeypatch.setattr("app.services.push_service.webpush", lambda **kwargs: None)


def _mock_webpush_failure(monkeypatch):
    def _raise(**kwargs):
        raise Exception("simulated push failure")

    monkeypatch.setattr("app.services.push_service.webpush", _raise)


def _sent_for(result, user_id):
    return [s for s in result["sent"] if s["user_id"] == str(user_id)]


def _log_exists(db, user_id, sent_on, slot):
    return (
        db.query(ReminderDispatchLog)
        .filter(
            ReminderDispatchLog.user_id == user_id,
            ReminderDispatchLog.sent_on == sent_on,
            ReminderDispatchLog.slot == slot,
        )
        .first()
        is not None
    )


# ----- AC1-AC3: meter-count eligibility -----

def test_ac1_exactly_two_meters_evaluation_proceeds(client, db):
    _, user_id = _register(client, f"ac1-{uuid.uuid4()}@example.com")
    anchor = TODAY - timedelta(days=10)
    _seed(db, user_id, anchor, TODAY)

    result = evaluate_switch_recommendation(db, user_id, TODAY)
    assert result is not None
    assert "$" not in result.explanation
    assert "sav" not in result.explanation.lower()


def test_ac2_zero_or_one_meter_skips(client, db):
    _, zero_meter_user = _register(client, f"ac2a-{uuid.uuid4()}@example.com")
    assert evaluate_switch_recommendation(db, zero_meter_user, TODAY) is None

    _, one_meter_user = _register(client, f"ac2b-{uuid.uuid4()}@example.com")
    _meter(db, one_meter_user, "Only Meter")
    assert evaluate_switch_recommendation(db, one_meter_user, TODAY) is None


def test_ac3_more_than_two_meters_skips(client, db):
    _, user_id = _register(client, f"ac3-{uuid.uuid4()}@example.com")
    anchor = TODAY - timedelta(days=10)
    _seed(db, user_id, anchor, TODAY)
    _meter(db, user_id, "Third Meter")

    assert evaluate_switch_recommendation(db, user_id, TODAY) is None


# ----- AC4: active meter resolution via resolve_active_meter_id -----

def test_ac4_active_meter_resolved_in_switched_state(client, db):
    _, user_id = _register(client, f"ac4-{uuid.uuid4()}@example.com")
    old_meter = _meter(db, user_id, "Old Meter")
    new_meter = _meter(db, user_id, "New Meter")

    # Give both meters a reading to satisfy the switch event's FK columns.
    switch_date = TODAY - timedelta(days=20)
    outgoing_reading = _reading(db, old_meter.id, switch_date, 500)
    incoming_reading = _reading(db, new_meter.id, switch_date, 0)
    db.add(
        MeterSwitchEvent(
            user_id=user_id,
            outgoing_meter_id=old_meter.id,
            incoming_meter_id=new_meter.id,
            outgoing_reading_id=outgoing_reading.id,
            incoming_reading_id=incoming_reading.id,
            reading_date=switch_date,
        )
    )
    db.commit()

    # New meter (created second, but active via the switch) gets its own
    # billing anchor and recommendation-worthy consumption.
    anchor = TODAY - timedelta(days=10)
    _reading(db, new_meter.id, anchor, 1000, is_billed=True)
    _reading(db, new_meter.id, TODAY, 1060)

    result = evaluate_switch_recommendation(db, user_id, TODAY)
    assert result is not None
    assert result.active_meter_id == new_meter.id
    assert result.standby_meter_id == old_meter.id


# ----- AC5: missing billing anchor -----

def test_ac5_no_billing_anchor_skips(client, db):
    _, user_id = _register(client, f"ac5-{uuid.uuid4()}@example.com")
    anchor = TODAY - timedelta(days=10)
    _seed(db, user_id, anchor, TODAY, active_billed=False)

    assert evaluate_switch_recommendation(db, user_id, TODAY) is None


# ----- AC6/AC7: ten-day evaluation boundary -----

def test_ac6_anchor_nine_days_old_skips(client, db):
    _, user_id = _register(client, f"ac6-{uuid.uuid4()}@example.com")
    anchor = TODAY - timedelta(days=9)
    _seed(db, user_id, anchor, TODAY)

    assert evaluate_switch_recommendation(db, user_id, TODAY) is None


def test_ac7_anchor_ten_days_old_evaluates(client, db):
    _, user_id = _register(client, f"ac7-{uuid.uuid4()}@example.com")
    anchor = TODAY - timedelta(days=10)
    _seed(db, user_id, anchor, TODAY)

    assert evaluate_switch_recommendation(db, user_id, TODAY) is not None


# ----- AC8/AC9: configured slabs, no hardcoded 100; safety buffer -----

def test_ac8_non_default_slabs_drive_projection_not_hardcoded_100(client, db):
    _, user_id = _register(client, f"ac8-{uuid.uuid4()}@example.com")
    anchor = TODAY - timedelta(days=10)
    slabs = (("0", 50), (50, 150), (150, None))
    _seed(db, user_id, anchor, TODAY, active_units=20, standby_units=0, active_slabs=slabs)

    result = evaluate_switch_recommendation(db, user_id, TODAY)
    assert result is not None
    assert result.active_next_slab_min == 50.0
    assert result.active_operational_threshold == 48.0


def test_ac9_safety_buffer_two_gives_threshold_98(client, db):
    _, user_id = _register(client, f"ac9-{uuid.uuid4()}@example.com")
    anchor = TODAY - timedelta(days=10)
    _seed(db, user_id, anchor, TODAY)

    result = evaluate_switch_recommendation(db, user_id, TODAY)
    assert result is not None
    assert result.active_next_slab_min == 100.0
    assert result.active_operational_threshold == 98.0


# ----- AC10/AC11: consumption rate / recent-rate projection -----

def test_ac10_rate_computed_and_projection_produced(client, db):
    _, user_id = _register(client, f"ac10-{uuid.uuid4()}@example.com")
    anchor = TODAY - timedelta(days=10)
    _seed(db, user_id, anchor, TODAY)

    result = evaluate_switch_recommendation(db, user_id, TODAY)
    assert result is not None
    # remaining=38, rate=6/day -> floor(38/6)=6
    assert result.recommended_switch_date == TODAY + timedelta(days=6)


def test_ac11_recent_rate_faster_than_overall_drives_earlier_projection(client, db):
    _, no_spike_user = _register(client, f"ac11a-{uuid.uuid4()}@example.com")
    anchor = TODAY - timedelta(days=10)
    _seed(db, no_spike_user, anchor, TODAY)
    baseline = evaluate_switch_recommendation(db, no_spike_user, TODAY)
    assert baseline is not None
    assert baseline.recommended_switch_date == TODAY + timedelta(days=6)

    _, spike_user = _register(client, f"ac11b-{uuid.uuid4()}@example.com")
    active_meter, _ = _seed(db, spike_user, anchor, TODAY)
    # Insert an intermediate reading showing a recent burst: +50 units in the
    # single day before "today", vs. +10 in the 9 days before that.
    _reading(db, active_meter.id, TODAY - timedelta(days=1), 1050)

    spiked = evaluate_switch_recommendation(db, spike_user, TODAY)
    assert spiked is not None
    # remaining=38, recent_rate=10/day -> floor(38/10)=3, earlier than 6.
    assert spiked.recommended_switch_date == TODAY + timedelta(days=3)
    assert spiked.recommended_switch_date < baseline.recommended_switch_date


# ----- AC12/AC13: billing-period estimation (median vs. fallback) -----

def _billing_period_scenario(db, user_id, include_history):
    anchor = TODAY - timedelta(days=68)
    active_meter, standby_meter = _seed(
        db, user_id, anchor, TODAY, active_units=70, standby_units=0
    )
    if include_history:
        # Two earlier billed readings on the active meter, 100 days apart
        # each -> median = 100, pushing the estimated billing-period end
        # well past the fallback's 30-day guess. update_anchor=False: these
        # feed the historical-interval pool but must not displace the
        # meter's *current* anchor (still the reading _seed just billed).
        _reading(db, active_meter.id, anchor - timedelta(days=200), 700, is_billed=True, update_anchor=False)
        _reading(db, active_meter.id, anchor - timedelta(days=100), 850, is_billed=True, update_anchor=False)
    return active_meter, standby_meter


def test_ac12_billing_period_uses_median_when_sufficient_history(client, db):
    _, user_id = _register(client, f"ac12-{uuid.uuid4()}@example.com")
    _billing_period_scenario(db, user_id, include_history=True)

    result = evaluate_switch_recommendation(db, user_id, TODAY)
    assert result is not None
    # remaining=28, rate=70/68 -> floor(28*68/70)=27
    assert result.recommended_switch_date == TODAY + timedelta(days=27)


def test_ac12b_duplicate_billed_dates_collapse_before_interval_calculation(client, db):
    """Regression guard for the real-data suppression bug: raw billed dates
    Jul 06 (x3), Aug 09 (x2) must reduce to the distinct dates Jul 06, Aug 09
    -> a single 34-day interval, not [0, 0, 34, 0]. With only one real
    interval (below the default min-2-intervals threshold), the estimate
    falls back to the 30-day default -- it must never collapse to 0 days
    (anchor.reading_date + 0), which is what the pre-fix code produced."""
    from app.services.electricity_insights_service import expected_billing_period_end

    _, user_id = _register(client, f"ac12b-{uuid.uuid4()}@example.com")
    meter = _meter(db, user_id, "Meter")

    earlier_date = date(2026, 7, 6)
    later_date = date(2026, 8, 9)
    for value in (500, 500, 500):
        _reading(db, meter.id, earlier_date, value, is_billed=True, update_anchor=False)
    anchor = None
    for value in (1000, 1000):
        anchor = _reading(db, meter.id, later_date, value, is_billed=True, update_anchor=False)

    result = expected_billing_period_end(db, [meter.id], anchor)

    assert result == later_date + timedelta(days=settings.meter_slab_default_billing_period_days)
    assert result != later_date  # must not collapse to the anchor date itself (the pre-fix bug)


def test_ac12c_worked_example_recommends_end_to_end_with_duplicate_billing_history(client, db):
    """The feature-spec §2 worked example (active ~60 units, standby ~0
    units, 100-unit boundary, 2-unit buffer) combined with a duplicate-dated
    billing history (as in AC12b) must still produce a populated
    recommendation once the other eligibility conditions are satisfied --
    proves the distinct-date fix resolves the end-to-end suppression, not
    just the isolated interval calculation. Before the fix, this exact
    setup returned None (opportunity_exists was forced False by the
    corrupted 0-day billing-period estimate)."""
    _, user_id = _register(client, f"ac12c-{uuid.uuid4()}@example.com")

    anchor_date = TODAY - timedelta(days=10)
    earlier_date = anchor_date - timedelta(days=34)

    active_meter = _meter(db, user_id, "Active Meter")
    standby_meter = _meter(db, user_id, "Standby Meter")

    # Duplicate-dated historical billing, exactly as in AC12b: 3 rows on
    # earlier_date, 2 rows on anchor_date (one of which becomes the real
    # current anchor) -- 5 raw billed rows, only 2 distinct dates, 34 days
    # apart.
    for value in (500, 500, 500):
        _reading(db, active_meter.id, earlier_date, value, is_billed=True, update_anchor=False)
    _reading(db, active_meter.id, anchor_date, 1000, is_billed=True, update_anchor=False)
    _reading(db, active_meter.id, anchor_date, 1000, is_billed=True, update_anchor=True)

    _reading(db, active_meter.id, TODAY, 1060)  # 60 units consumed since the anchor
    _reading(db, standby_meter.id, anchor_date, 0)
    _reading(db, standby_meter.id, TODAY, 0)

    result = evaluate_switch_recommendation(db, user_id, TODAY)
    assert result is not None
    assert result.active_cumulative_units == 60.0
    assert result.standby_cumulative_units == 0.0


def test_ac13_billing_period_falls_back_to_default_when_insufficient_history(client, db):
    _, user_id = _register(client, f"ac13-{uuid.uuid4()}@example.com")
    _billing_period_scenario(db, user_id, include_history=False)

    # With only the fallback (30 days), the anchor (68 days ago) means the
    # estimated billing period already ended 38 days ago -> no opportunity.
    assert evaluate_switch_recommendation(db, user_id, TODAY) is None


# ----- AC14/AC15/AC16: standby evaluation -----

def test_ac14_threshold_projected_before_billing_end_evaluates_standby(client, db):
    _, user_id = _register(client, f"ac14-{uuid.uuid4()}@example.com")
    anchor = TODAY - timedelta(days=10)
    _seed(db, user_id, anchor, TODAY)

    assert evaluate_switch_recommendation(db, user_id, TODAY) is not None


def test_ac15_standby_without_meaningful_headroom_skips(client, db):
    _, user_id = _register(client, f"ac15-{uuid.uuid4()}@example.com")
    anchor = TODAY - timedelta(days=10)
    _seed(db, user_id, anchor, TODAY, active_units=60, standby_units=90)

    assert evaluate_switch_recommendation(db, user_id, TODAY) is None


def test_ac16_standby_with_meaningful_headroom_is_eligible(client, db):
    _, user_id = _register(client, f"ac16-{uuid.uuid4()}@example.com")
    anchor = TODAY - timedelta(days=10)
    _seed(db, user_id, anchor, TODAY, active_units=60, standby_units=0)

    assert evaluate_switch_recommendation(db, user_id, TODAY) is not None


# ----- AC17: both meters near threshold -> no blind switch -----

def test_ac17_both_meters_near_threshold_no_blind_switch(client, db):
    _, user_id = _register(client, f"ac17-{uuid.uuid4()}@example.com")
    anchor = TODAY - timedelta(days=25)
    _seed(db, user_id, anchor, TODAY, active_units=98, standby_units=99)

    assert evaluate_switch_recommendation(db, user_id, TODAY) is None


# ----- AC18: recommended switch date, no extra buffer -----

def test_ac18_recommended_switch_date_has_no_extra_buffer(client, db):
    _, user_id = _register(client, f"ac18-{uuid.uuid4()}@example.com")
    anchor = TODAY - timedelta(days=10)
    _seed(db, user_id, anchor, TODAY)

    result = evaluate_switch_recommendation(db, user_id, TODAY)
    assert result is not None
    assert result.recommended_switch_date == TODAY + timedelta(days=6)


# ----- AC19/AC20/AC21: recipients -----

def test_ac19_owner_receives_push(client, db, monkeypatch):
    _, owner_id = _register(client, f"ac19-{uuid.uuid4()}@example.com")
    _enable_feature(db, owner_id)
    _add_subscription(db, owner_id)
    _mock_webpush_success(monkeypatch)
    _freeze(monkeypatch, TODAY)

    anchor = TODAY - timedelta(days=10)
    _seed(db, owner_id, anchor, TODAY)

    result = PushService.dispatch_meter_slab_recommendation(db)
    sent = _sent_for(result, owner_id)
    assert len(sent) == 1
    assert sent[0]["subscriptions"] == 1


def test_ac20_shared_user_with_access_to_both_meters_receives_push(client, db, monkeypatch):
    _, owner_id = _register(client, f"ac20owner-{uuid.uuid4()}@example.com")
    _, shared_id = _register(client, f"ac20shared-{uuid.uuid4()}@example.com")
    _enable_feature(db, owner_id)
    _enable_feature(db, shared_id)
    _add_subscription(db, shared_id)
    _mock_webpush_success(monkeypatch)
    _freeze(monkeypatch, TODAY)

    anchor = TODAY - timedelta(days=10)
    active_meter, standby_meter = _seed(db, owner_id, anchor, TODAY)
    _share(db, active_meter.id, shared_id)
    _share(db, standby_meter.id, shared_id)

    result = PushService.dispatch_meter_slab_recommendation(db)
    sent = _sent_for(result, shared_id)
    assert len(sent) == 1


def test_ac21_owner_and_shared_user_deduped_independently(client, db, monkeypatch):
    _, owner_id = _register(client, f"ac21owner-{uuid.uuid4()}@example.com")
    _, shared_id = _register(client, f"ac21shared-{uuid.uuid4()}@example.com")
    _enable_feature(db, owner_id)
    _enable_feature(db, shared_id)
    _add_subscription(db, owner_id)
    _add_subscription(db, shared_id)
    _mock_webpush_success(monkeypatch)
    _freeze(monkeypatch, TODAY)

    anchor = TODAY - timedelta(days=10)
    active_meter, standby_meter = _seed(db, owner_id, anchor, TODAY)
    _share(db, active_meter.id, shared_id)
    _share(db, standby_meter.id, shared_id)

    active_meter_row = db.query(Meter).filter(Meter.id == active_meter.id).first()
    slot = f"meter_slab_recommendation_{active_meter_row.last_billed_reading_id}"
    # Pre-seed the shared user as already notified today; the owner is not.
    db.add(ReminderDispatchLog(user_id=shared_id, sent_on=TODAY, slot=slot))
    db.commit()

    result = PushService.dispatch_meter_slab_recommendation(db)
    assert len(_sent_for(result, owner_id)) == 1
    assert len(_sent_for(result, shared_id)) == 0


# ----- AC22/AC22b: daily dedup, next-day re-notification -----

def test_ac22_second_dispatch_same_day_does_not_resend(client, db, monkeypatch):
    _, user_id = _register(client, f"ac22-{uuid.uuid4()}@example.com")
    _enable_feature(db, user_id)
    _add_subscription(db, user_id)
    _mock_webpush_success(monkeypatch)
    _freeze(monkeypatch, TODAY)

    anchor = TODAY - timedelta(days=10)
    _seed(db, user_id, anchor, TODAY)

    first = PushService.dispatch_meter_slab_recommendation(db)
    assert len(_sent_for(first, user_id)) == 1

    second = PushService.dispatch_meter_slab_recommendation(db)
    assert len(_sent_for(second, user_id)) == 0


def test_ac22b_next_day_dispatch_renotifies_when_still_valid(client, db, monkeypatch):
    _, user_id = _register(client, f"ac22b-{uuid.uuid4()}@example.com")
    _enable_feature(db, user_id)
    _add_subscription(db, user_id)
    _mock_webpush_success(monkeypatch)

    day0 = TODAY
    _freeze(monkeypatch, day0)
    anchor = day0 - timedelta(days=10)
    _seed(db, user_id, anchor, day0)

    first = PushService.dispatch_meter_slab_recommendation(db)
    assert len(_sent_for(first, user_id)) == 1

    _freeze(monkeypatch, day0 + timedelta(days=1))
    second = PushService.dispatch_meter_slab_recommendation(db)
    assert len(_sent_for(second, user_id)) == 1


# ----- AC23: re-evaluate after a switch -----

def test_ac23_switch_stops_the_obsolete_recommendation(client, db, monkeypatch):
    _, user_id = _register(client, f"ac23-{uuid.uuid4()}@example.com")
    _enable_feature(db, user_id)
    _add_subscription(db, user_id)
    _mock_webpush_success(monkeypatch)

    day0 = TODAY
    _freeze(monkeypatch, day0)
    anchor = day0 - timedelta(days=10)
    old_meter, new_meter = _seed(db, user_id, anchor, day0, active_label="Old Meter", standby_label="New Meter")

    first = PushService.dispatch_meter_slab_recommendation(db)
    assert len(_sent_for(first, user_id)) == 1

    # Switch to the standby meter, which has no billing anchor of its own.
    switch_date = day0
    outgoing_reading = _reading(db, old_meter.id, switch_date, 2000)
    incoming_reading = _reading(db, new_meter.id, switch_date, 0)
    db.add(
        MeterSwitchEvent(
            user_id=user_id,
            outgoing_meter_id=old_meter.id,
            incoming_meter_id=new_meter.id,
            outgoing_reading_id=outgoing_reading.id,
            incoming_reading_id=incoming_reading.id,
            reading_date=switch_date,
        )
    )
    db.commit()

    _freeze(monkeypatch, day0 + timedelta(days=1))
    second = PushService.dispatch_meter_slab_recommendation(db)
    assert len(_sent_for(second, user_id)) == 0


# ----- AC24: new billing anchor starts a new lifecycle -----

def test_ac24_new_billed_reading_starts_a_new_notification_lifecycle(client, db, monkeypatch):
    _, user_id = _register(client, f"ac24-{uuid.uuid4()}@example.com")
    _enable_feature(db, user_id)
    _add_subscription(db, user_id)
    _mock_webpush_success(monkeypatch)

    day0 = date(2026, 1, 1)
    _freeze(monkeypatch, day0)
    r1_anchor = day0 - timedelta(days=10)
    active_meter, _standby = _seed(db, user_id, r1_anchor, day0)
    active_meter_row = db.query(Meter).filter(Meter.id == active_meter.id).first()
    slot1 = f"meter_slab_recommendation_{active_meter_row.last_billed_reading_id}"

    first = PushService.dispatch_meter_slab_recommendation(db)
    assert len(_sent_for(first, user_id)) == 1
    assert _log_exists(db, user_id, day0, slot1)

    # A new bill is logged 5 days later, resetting the billing anchor.
    r2_date = day0 + timedelta(days=5)
    r2 = _reading(db, active_meter.id, r2_date, 5000, is_billed=True)
    # 10 days after the NEW anchor, consumption builds up again the same way.
    day25 = r2_date + timedelta(days=10)
    _reading(db, active_meter.id, day25, 5060)

    _freeze(monkeypatch, day25)
    slot2 = f"meter_slab_recommendation_{r2.id}"
    assert slot1 != slot2

    second = PushService.dispatch_meter_slab_recommendation(db)
    assert len(_sent_for(second, user_id)) == 1
    assert _log_exists(db, user_id, day25, slot2)


# ----- AC25: timezone-aware day math -----

def test_ac25_uses_configured_timezone_not_naive_utc(client, db, monkeypatch):
    _, user_id = _register(client, f"ac25-{uuid.uuid4()}@example.com")
    _enable_feature(db, user_id)
    _add_subscription(db, user_id)
    _mock_webpush_success(monkeypatch)
    monkeypatch.setattr(settings, "reminder_timezone", "Asia/Kolkata")

    # 00:30 IST on the 26th is 19:00 UTC on the 25th -- a classic
    # cross-midnight case. The anchor is exactly 10 Kolkata-local days back,
    # but only 9 UTC-calendar days back.
    fixed_now = datetime(2026, 6, 26, 0, 30, tzinfo=ZoneInfo("Asia/Kolkata"))
    monkeypatch.setattr("app.core.timezone.local_now", lambda: fixed_now)
    assert fixed_now.astimezone(ZoneInfo("UTC")).date() == date(2026, 6, 25)

    anchor = date(2026, 6, 16)
    _seed(db, user_id, anchor, date(2026, 6, 26))

    result = PushService.dispatch_meter_slab_recommendation(db)
    assert len(_sent_for(result, user_id)) == 1


# ----- AC26: push failure doesn't consume the dedup slot -----

def test_ac26_push_failure_does_not_consume_dedup_slot(client, db, monkeypatch):
    _, user_id = _register(client, f"ac26-{uuid.uuid4()}@example.com")
    _enable_feature(db, user_id)
    _add_subscription(db, user_id)
    _freeze(monkeypatch, TODAY)

    anchor = TODAY - timedelta(days=10)
    active_meter, _ = _seed(db, user_id, anchor, TODAY)
    active_meter_row = db.query(Meter).filter(Meter.id == active_meter.id).first()
    slot = f"meter_slab_recommendation_{active_meter_row.last_billed_reading_id}"

    _mock_webpush_failure(monkeypatch)
    first = PushService.dispatch_meter_slab_recommendation(db)
    assert len(_sent_for(first, user_id)) == 1
    assert first["sent"][0]["subscriptions"] == 0
    assert not _log_exists(db, user_id, TODAY, slot)

    second = PushService.dispatch_meter_slab_recommendation(db)
    assert not _log_exists(db, user_id, TODAY, slot)

    _mock_webpush_success(monkeypatch)
    third = PushService.dispatch_meter_slab_recommendation(db)
    assert len(_sent_for(third, user_id)) == 1
    assert _log_exists(db, user_id, TODAY, slot)


# ----- AC27: dispatch authentication unchanged -----

def test_ac27_dispatch_requires_correct_token(client, monkeypatch):
    monkeypatch.setattr(settings, "dispatch_token", "test-token-for-ac27")

    wrong = client.post("/api/v1/push/dispatch", params={"token": "not-it"})
    assert wrong.status_code == 401

    correct = client.post("/api/v1/push/dispatch", params={"token": "test-token-for-ac27"})
    assert correct.status_code == 200
    body = correct.json()
    assert isinstance(body["processed_users"], int)
    assert isinstance(body["sent"], list)
    assert isinstance(body["errors"], list)


# ----- AC28: feature flag gates dispatch -----

def test_ac28_feature_flag_disabled_skips_candidate(client, db, monkeypatch):
    _, user_id = _register(client, f"ac28-{uuid.uuid4()}@example.com")
    # Deliberately not enabling the feature flag for this user.
    _add_subscription(db, user_id)
    _mock_webpush_success(monkeypatch)
    _freeze(monkeypatch, TODAY)

    anchor = TODAY - timedelta(days=10)
    _seed(db, user_id, anchor, TODAY)

    result = PushService.dispatch_meter_slab_recommendation(db)
    assert len(_sent_for(result, user_id)) == 0


# ----- AC29: no monetary/guaranteed-savings claim -----

def test_ac29_push_copy_has_no_monetary_or_savings_claim():
    from app.services.push_service import METER_SLAB_MESSAGE

    title, body = METER_SLAB_MESSAGE
    combined = f"{title} {body}"
    assert "$" not in combined
    assert "sav" not in combined.lower()
    assert title == "⚡ Consider switching meters"
    assert (
        body
        == "Your usage is approaching the next slab. Switching your active meter may help keep one meter within the lower usage slab."
    )


# ----- Edge cases -----

def test_edge_case_zero_slab_thresholds_configured(client, db):
    _, user_id = _register(client, f"edge-zero-slabs-{uuid.uuid4()}@example.com")
    anchor = TODAY - timedelta(days=10)
    _seed(db, user_id, anchor, TODAY, active_slabs=())

    assert evaluate_switch_recommendation(db, user_id, TODAY) is None


def test_edge_case_zero_consumption_skips(client, db):
    _, user_id = _register(client, f"edge-zero-consumption-{uuid.uuid4()}@example.com")
    anchor = TODAY - timedelta(days=10)
    _seed(db, user_id, anchor, TODAY, active_units=0)

    assert evaluate_switch_recommendation(db, user_id, TODAY) is None


def test_edge_case_active_meter_already_in_open_ended_top_slab(client, db):
    _, user_id = _register(client, f"edge-top-slab-{uuid.uuid4()}@example.com")
    anchor = TODAY - timedelta(days=10)
    _seed(db, user_id, anchor, TODAY, active_units=150)

    assert evaluate_switch_recommendation(db, user_id, TODAY) is None


def test_edge_case_same_day_duplicate_reading_falls_back_to_overall_rate(client, db):
    _, user_id = _register(client, f"edge-dup-reading-{uuid.uuid4()}@example.com")
    anchor = TODAY - timedelta(days=10)
    active_meter = _meter(db, user_id, "Active Meter")
    standby_meter = _meter(db, user_id, "Standby Meter")
    _reading(db, active_meter.id, anchor, 1000, is_billed=True)
    # Two readings sharing today's date, inserted in order, so the two
    # most-recent readings tie on reading_date (created_at breaks the tie
    # for which one is "latest", but recent_rate must still refuse to
    # divide by zero days).
    _reading(db, active_meter.id, TODAY, 1055)
    _reading(db, active_meter.id, TODAY, 1060)
    _reading(db, standby_meter.id, anchor, 0)
    _reading(db, standby_meter.id, TODAY, 0)

    result = evaluate_switch_recommendation(db, user_id, TODAY)
    assert result is not None
    assert result.active_cumulative_units == 60.0
    assert result.recommended_switch_date == TODAY + timedelta(days=6)


# ----- Read-path tests (§16) -----

def test_read_path_matches_shared_evaluation_exactly(client, db, monkeypatch):
    headers, user_id = _register(client, f"read30-{uuid.uuid4()}@example.com")
    _enable_feature(db, user_id)
    _freeze(monkeypatch, TODAY)

    anchor = TODAY - timedelta(days=10)
    _seed(db, user_id, anchor, TODAY)

    direct = evaluate_switch_recommendation(db, user_id, TODAY)
    assert direct is not None

    response = client.get("/api/v1/electricity/insights", headers=headers)
    assert response.status_code == 200
    body = response.json()["slab_recommendation"]
    assert body is not None
    assert body["active_meter_id"] == str(direct.active_meter_id)
    assert body["active_meter_label"] == direct.active_meter_label
    assert body["standby_meter_id"] == str(direct.standby_meter_id)
    assert body["standby_meter_label"] == direct.standby_meter_label
    assert body["active_cumulative_units"] == direct.active_cumulative_units
    assert body["active_next_slab_min"] == direct.active_next_slab_min
    assert body["active_operational_threshold"] == direct.active_operational_threshold
    assert body["standby_cumulative_units"] == direct.standby_cumulative_units
    assert body["standby_next_slab_min"] == direct.standby_next_slab_min
    assert body["standby_operational_threshold"] == direct.standby_operational_threshold
    assert body["recommended_switch_date"] == direct.recommended_switch_date.isoformat()
    assert body["explanation"] == direct.explanation


def test_read_path_null_when_not_eligible(client, db, monkeypatch):
    headers, user_id = _register(client, f"read31-{uuid.uuid4()}@example.com")
    _enable_feature(db, user_id)
    _freeze(monkeypatch, TODAY)
    _meter(db, user_id, "Only Meter")

    response = client.get("/api/v1/electricity/insights", headers=headers)
    assert response.status_code == 200
    assert response.json()["slab_recommendation"] is None


def test_read_path_ignores_reminder_dispatch_log(client, db, monkeypatch):
    headers, user_id = _register(client, f"read32-{uuid.uuid4()}@example.com")
    _enable_feature(db, user_id)
    _freeze(monkeypatch, TODAY)

    anchor = TODAY - timedelta(days=10)
    active_meter, _ = _seed(db, user_id, anchor, TODAY)
    active_meter_row = db.query(Meter).filter(Meter.id == active_meter.id).first()
    slot = f"meter_slab_recommendation_{active_meter_row.last_billed_reading_id}"
    db.add(ReminderDispatchLog(user_id=user_id, sent_on=TODAY, slot=slot))
    db.commit()

    response = client.get("/api/v1/electricity/insights", headers=headers)
    assert response.status_code == 200
    assert response.json()["slab_recommendation"] is not None


def test_read_path_403_without_feature_flag(client, db):
    headers, user_id = _register(client, f"read33-{uuid.uuid4()}@example.com")
    # Feature flag deliberately not enabled.
    response = client.get("/api/v1/electricity/insights", headers=headers)
    assert response.status_code == 403


def test_read_path_existing_meters_fields_unaffected(client, db, monkeypatch):
    headers, user_id = _register(client, f"read34-{uuid.uuid4()}@example.com")
    _enable_feature(db, user_id)
    _freeze(monkeypatch, TODAY)

    anchor = TODAY - timedelta(days=10)
    _seed(db, user_id, anchor, TODAY)

    response = client.get("/api/v1/electricity/insights", headers=headers)
    assert response.status_code == 200
    body = response.json()
    assert "meters" in body
    assert len(body["meters"]) == 2
    for meter_entry in body["meters"]:
        for key in (
            "meter_id",
            "label",
            "status",
            "is_owner",
            "cumulative_units",
            "current_bracket",
            "next_slab_min",
            "nudge_text",
        ):
            assert key in meter_entry


# ----- Settings are read live, not baked in (test #35) -----

def test_settings_safety_buffer_units_is_read_live(client, db, monkeypatch):
    _, user_id = _register(client, f"settings-buffer-{uuid.uuid4()}@example.com")
    monkeypatch.setattr(settings, "meter_slab_safety_buffer_units", 5)

    anchor = TODAY - timedelta(days=10)
    _seed(db, user_id, anchor, TODAY)

    result = evaluate_switch_recommendation(db, user_id, TODAY)
    assert result is not None
    assert result.active_operational_threshold == 95.0


def test_settings_min_evaluation_days_is_read_live(client, db, monkeypatch):
    _, user_id = _register(client, f"settings-mineval-{uuid.uuid4()}@example.com")
    monkeypatch.setattr(settings, "meter_slab_min_evaluation_days", 15)

    anchor = TODAY - timedelta(days=10)
    _seed(db, user_id, anchor, TODAY)

    # 10 days elapsed would normally qualify (default is 10); with the
    # setting raised to 15, it must not.
    assert evaluate_switch_recommendation(db, user_id, TODAY) is None


def test_settings_default_billing_period_days_is_read_live(client, db, monkeypatch):
    _, user_id = _register(client, f"settings-billingdefault-{uuid.uuid4()}@example.com")
    monkeypatch.setattr(settings, "meter_slab_default_billing_period_days", 5)

    anchor = TODAY - timedelta(days=10)
    _seed(db, user_id, anchor, TODAY)

    # With the default fallback of 30 days this would recommend; shrinking
    # it to 5 pushes the estimated billing-period end into the past.
    assert evaluate_switch_recommendation(db, user_id, TODAY) is None


def test_settings_min_billing_intervals_for_estimate_is_read_live(client, db, monkeypatch):
    _, user_id = _register(client, f"settings-mininterval-{uuid.uuid4()}@example.com")
    _billing_period_scenario(db, user_id, include_history=True)

    # With the default threshold of 2, this scenario's 2 historical
    # intervals are trusted (median 100) and it recommends (test AC12).
    # Raising the threshold makes them insufficient, falling back to the
    # 30-day default and losing the opportunity.
    monkeypatch.setattr(settings, "meter_slab_min_billing_intervals_for_estimate", 5)
    assert evaluate_switch_recommendation(db, user_id, TODAY) is None


# ----- Settings validation (adversarial-review findings #1/#2) -----
#
# meter_slab_min_evaluation_days=0 previously let elapsed_days reach 0,
# raising an unhandled ZeroDivisionError in evaluate_switch_recommendation's
# overall_rate = cumulative_active / elapsed_days (uncaught on the read
# path, since app/api/electricity.py has no try/except around get_insights).
#
# meter_slab_min_billing_intervals_for_estimate=0 previously let a user with
# zero historical billing intervals (the common case: only the current
# anchor is billed) pass the "sufficient history" check and call
# statistics.median([]), raising an unhandled StatisticsError on the same
# unprotected read path.
#
# Field(ge=...) constraints on Settings close both by failing fast at
# Settings() construction (i.e. at app startup from env vars) rather than
# inside a request.

def _settings_kwargs(**overrides):
    return {
        "database_url": settings.database_url,
        "jwt_secret": settings.jwt_secret,
        **overrides,
    }


def test_settings_reject_min_evaluation_days_below_one():
    with pytest.raises(ValidationError):
        Settings(**_settings_kwargs(meter_slab_min_evaluation_days=0))


def test_settings_accept_min_evaluation_days_at_one():
    s = Settings(**_settings_kwargs(meter_slab_min_evaluation_days=1))
    assert s.meter_slab_min_evaluation_days == 1


def test_settings_reject_safety_buffer_units_below_zero():
    with pytest.raises(ValidationError):
        Settings(**_settings_kwargs(meter_slab_safety_buffer_units=-1))


def test_settings_accept_safety_buffer_units_at_zero():
    s = Settings(**_settings_kwargs(meter_slab_safety_buffer_units=0))
    assert s.meter_slab_safety_buffer_units == 0


def test_settings_reject_default_billing_period_days_below_one():
    with pytest.raises(ValidationError):
        Settings(**_settings_kwargs(meter_slab_default_billing_period_days=0))


def test_settings_accept_default_billing_period_days_at_one():
    s = Settings(**_settings_kwargs(meter_slab_default_billing_period_days=1))
    assert s.meter_slab_default_billing_period_days == 1


def test_settings_reject_min_billing_intervals_for_estimate_below_one():
    with pytest.raises(ValidationError):
        Settings(**_settings_kwargs(meter_slab_min_billing_intervals_for_estimate=0))


def test_settings_accept_min_billing_intervals_for_estimate_at_one():
    s = Settings(**_settings_kwargs(meter_slab_min_billing_intervals_for_estimate=1))
    assert s.meter_slab_min_billing_intervals_for_estimate == 1
