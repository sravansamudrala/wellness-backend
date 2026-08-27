import uuid
from datetime import date, timedelta

from app.database.session import SessionLocal
from app.models.feature_flag import FeatureFlag

FEATURE_KEY = "electricity_tracker"


def _user_id_from_response(response):
    return response.json()["id"]


def _register_and_get_headers(client, email):
    response = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "supersecret123"},
    )
    token = response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _enable_feature(auth_headers, client):
    """The router is default-deny — every test needs this before hitting any
    /api/v1/electricity/* endpoint."""
    me = client.get("/api/v1/auth/me", headers=auth_headers)
    user_id = me.json()["id"]

    db = SessionLocal()
    try:
        db.add(FeatureFlag(user_id=user_id, feature_key=FEATURE_KEY, enabled=True))
        db.commit()
    finally:
        db.close()
    return user_id


def _create_meter(client, auth_headers, label, slab_thresholds=None):
    response = client.post(
        "/api/v1/electricity/meters",
        json={"label": label, "slab_thresholds": slab_thresholds or []},
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_electricity_endpoints_are_403_without_the_feature_flag(client, auth_headers):
    response = client.get("/api/v1/electricity/meters", headers=auth_headers)
    assert response.status_code == 403


def test_electricity_endpoints_are_reachable_once_flag_is_enabled(client, auth_headers):
    _enable_feature(auth_headers, client)
    response = client.get("/api/v1/electricity/meters", headers=auth_headers)
    assert response.status_code == 200
    assert response.json() == []


def test_max_two_meters_per_user(client, auth_headers):
    _enable_feature(auth_headers, client)
    _create_meter(client, auth_headers, "Old Meter")
    _create_meter(client, auth_headers, "New Meter")

    third = client.post(
        "/api/v1/electricity/meters",
        json={"label": "Third Meter"},
        headers=auth_headers,
    )
    assert third.status_code == 400


def test_reading_delta_and_rejects_a_decrease(client, auth_headers):
    _enable_feature(auth_headers, client)
    meter = _create_meter(client, auth_headers, "Meter A")
    meter_id = meter["id"]

    baseline = client.post(
        f"/api/v1/electricity/meters/{meter_id}/readings",
        json={"reading_value": 1000, "reading_date": "2026-08-01"},
        headers=auth_headers,
    )
    assert baseline.status_code == 200
    assert baseline.json()["units_consumed"] is None

    second = client.post(
        f"/api/v1/electricity/meters/{meter_id}/readings",
        json={"reading_value": 1042, "reading_date": "2026-08-02"},
        headers=auth_headers,
    )
    assert second.status_code == 200
    assert second.json()["units_consumed"] == 42

    decreasing = client.post(
        f"/api/v1/electricity/meters/{meter_id}/readings",
        json={"reading_value": 1000, "reading_date": "2026-08-03"},
        headers=auth_headers,
    )
    assert decreasing.status_code == 400


def test_switch_event_creates_both_readings_and_resets_the_billed_meter(client, auth_headers):
    _enable_feature(auth_headers, client)
    old_meter = _create_meter(client, auth_headers, "Old Meter")
    new_meter = _create_meter(client, auth_headers, "New Meter")

    # No switch yet — active meter defaults to the first one created.
    client.post(
        f"/api/v1/electricity/meters/{old_meter['id']}/readings",
        json={"reading_value": 500, "reading_date": "2026-08-01"},
        headers=auth_headers,
    )

    switch = client.post(
        "/api/v1/electricity/switch-events",
        json={
            "incoming_meter_id": new_meter["id"],
            "reading_date": "2026-08-03",
            "outgoing_reading_value": 588,
            "incoming_reading_value": 100,
            "is_billed_reading": True,
        },
        headers=auth_headers,
    )
    assert switch.status_code == 200, switch.text
    body = switch.json()
    assert body["outgoing_meter_id"] == old_meter["id"]
    assert body["incoming_meter_id"] == new_meter["id"]
    assert body["outgoing_reading"]["units_consumed"] == 88
    assert body["outgoing_reading"]["is_billed_reading"] is True
    assert body["incoming_reading"]["units_consumed"] is None

    insights = client.get("/api/v1/electricity/insights", headers=auth_headers)
    assert insights.status_code == 200
    by_id = {m["meter_id"]: m for m in insights.json()["meters"]}

    # Billed reading became the outgoing meter's anchor — its cumulative
    # resets to 0 immediately, even though its all-time reading is 588.
    assert by_id[old_meter["id"]]["cumulative_units"] == 0
    assert by_id[old_meter["id"]]["status"] == "standby"
    assert by_id[new_meter["id"]]["status"] == "active"
    assert by_id[new_meter["id"]]["cumulative_units"] == 0


def test_insights_bracket_and_nudge_tone_before_and_after_threshold(client, auth_headers):
    _enable_feature(auth_headers, client)
    meter = _create_meter(
        client,
        auth_headers,
        "Meter A",
        slab_thresholds=[{"slab_min": 0, "slab_max": 100}, {"slab_min": 100, "slab_max": None}],
    )
    meter_id = meter["id"]

    client.post(
        f"/api/v1/electricity/meters/{meter_id}/readings",
        json={"reading_value": 1000, "reading_date": "2026-08-01"},
        headers=auth_headers,
    )
    client.post(
        f"/api/v1/electricity/meters/{meter_id}/readings",
        json={"reading_value": 1042, "reading_date": "2026-08-02"},
        headers=auth_headers,
    )

    insights = client.get("/api/v1/electricity/insights", headers=auth_headers).json()
    entry = insights["meters"][0]
    assert entry["cumulative_units"] == 42
    assert entry["current_bracket"]["slab_min"] == 0
    assert entry["next_slab_min"] == 100
    assert "comfortably inside" in entry["nudge_text"]

    # Push past the boundary.
    client.post(
        f"/api/v1/electricity/meters/{meter_id}/readings",
        json={"reading_value": 1120, "reading_date": "2026-08-03"},
        headers=auth_headers,
    )
    insights_after = client.get("/api/v1/electricity/insights", headers=auth_headers).json()
    entry_after = insights_after["meters"][0]
    assert entry_after["cumulative_units"] == 120
    assert entry_after["current_bracket"]["slab_min"] == 100
    assert entry_after["next_slab_min"] is None
    assert "top slab" in entry_after["nudge_text"]


def test_insights_daily_rate_and_projection_fields(client, auth_headers):
    _enable_feature(auth_headers, client)
    meter = _create_meter(
        client,
        auth_headers,
        "Meter A",
        slab_thresholds=[{"slab_min": 0, "slab_max": 100}, {"slab_min": 100, "slab_max": None}],
    )
    meter_id = meter["id"]

    today = date.today()
    anchor_date = today - timedelta(days=10)

    # Only one reading so far — not enough data for a rate yet, even though
    # real wall-clock time has passed since it was logged.
    client.post(
        f"/api/v1/electricity/meters/{meter_id}/readings",
        json={
            "reading_value": 1000,
            "reading_date": anchor_date.isoformat(),
            "is_billed_reading": True,
        },
        headers=auth_headers,
    )
    single_reading_insights = client.get("/api/v1/electricity/insights", headers=auth_headers).json()
    entry = single_reading_insights["meters"][0]
    assert entry["daily_rate"] is None
    assert entry["recent_rate"] is None
    assert entry["projected_units_at_billing_end"] is None

    # A second reading 10 days later, 50 units consumed -> 5 units/day.
    client.post(
        f"/api/v1/electricity/meters/{meter_id}/readings",
        json={"reading_value": 1050, "reading_date": today.isoformat()},
        headers=auth_headers,
    )
    insights = client.get("/api/v1/electricity/insights", headers=auth_headers).json()
    entry = insights["meters"][0]
    assert entry["daily_rate"] == 5.0
    assert entry["recent_rate"] == 5.0
    assert entry["expected_billing_period_end"] is not None
    assert entry["projected_units_at_billing_end"] >= entry["cumulative_units"]


def test_standby_meter_gets_rate_but_not_projection(client, auth_headers):
    _enable_feature(auth_headers, client)
    # First-created meter defaults to active; the second is standby with no
    # switch event needed for this test.
    _create_meter(client, auth_headers, "Active Meter")
    standby = _create_meter(client, auth_headers, "Standby Meter")
    standby_id = standby["id"]

    today = date.today()
    anchor_date = today - timedelta(days=10)

    # 10 days, 50 units -> 5.0 units/day, from when this meter was last
    # actually read (its own reading span), not from wall-clock "today".
    client.post(
        f"/api/v1/electricity/meters/{standby_id}/readings",
        json={"reading_value": 1000, "reading_date": anchor_date.isoformat(), "is_billed_reading": True},
        headers=auth_headers,
    )
    client.post(
        f"/api/v1/electricity/meters/{standby_id}/readings",
        json={"reading_value": 1050, "reading_date": today.isoformat()},
        headers=auth_headers,
    )

    insights = client.get("/api/v1/electricity/insights", headers=auth_headers).json()
    entry = next(m for m in insights["meters"] if m["meter_id"] == standby_id)
    assert entry["status"] == "standby"
    # Historical rate is still meaningful even for a standby meter.
    assert entry["daily_rate"] == 5.0
    assert entry["recent_rate"] == 5.0
    # Forward projection only applies to the meter you're actively drawing
    # from — a standby meter isn't accumulating toward a future bill.
    assert entry["expected_billing_period_end"] is None
    assert entry["projected_units_at_billing_end"] is None
    assert entry["cumulative_units"] == 50


def test_billed_amount_round_trips_through_list_readings(client, auth_headers):
    _enable_feature(auth_headers, client)
    meter = _create_meter(client, auth_headers, "Meter A")
    meter_id = meter["id"]

    client.post(
        f"/api/v1/electricity/meters/{meter_id}/readings",
        json={"reading_value": 1000, "reading_date": "2026-08-01"},
        headers=auth_headers,
    )
    response = client.post(
        f"/api/v1/electricity/meters/{meter_id}/readings",
        json={
            "reading_value": 1150,
            "reading_date": "2026-09-01",
            "is_billed_reading": True,
            "billed_amount": 423.5,
        },
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text
    assert response.json()["billed_amount"] == 423.5

    readings = client.get(
        f"/api/v1/electricity/meters/{meter_id}/readings", headers=auth_headers
    ).json()
    billed = next(r for r in readings if r["is_billed_reading"])
    assert billed["billed_amount"] == 423.5

    # A non-billed reading with no amount entered stays null.
    unbilled = next(r for r in readings if not r["is_billed_reading"])
    assert unbilled["billed_amount"] is None


def test_resubmitting_a_billed_reading_same_day_corrects_it_instead_of_duplicating(
    client, auth_headers
):
    _enable_feature(auth_headers, client)
    meter = _create_meter(client, auth_headers, "Meter A")
    meter_id = meter["id"]

    client.post(
        f"/api/v1/electricity/meters/{meter_id}/readings",
        json={"reading_value": 1000, "reading_date": "2026-08-01"},
        headers=auth_headers,
    )

    first_bill = client.post(
        f"/api/v1/electricity/meters/{meter_id}/readings",
        json={
            "reading_value": 1100,
            "reading_date": "2026-08-02",
            "is_billed_reading": True,
            "billed_amount": 300,
        },
        headers=auth_headers,
    )
    assert first_bill.status_code == 200, first_bill.text
    first_id = first_bill.json()["id"]
    assert first_bill.json()["units_consumed"] == 100

    # Typo caught immediately — resubmit the same day's bill with the
    # correct value. Should update the same row, not create a second one.
    corrected = client.post(
        f"/api/v1/electricity/meters/{meter_id}/readings",
        json={
            "reading_value": 1120,
            "reading_date": "2026-08-02",
            "is_billed_reading": True,
            "billed_amount": 320,
        },
        headers=auth_headers,
    )
    assert corrected.status_code == 200, corrected.text
    assert corrected.json()["id"] == first_id
    assert corrected.json()["units_consumed"] == 120
    assert corrected.json()["billed_amount"] == 320

    readings = client.get(
        f"/api/v1/electricity/meters/{meter_id}/readings", headers=auth_headers
    ).json()
    billed_readings = [r for r in readings if r["is_billed_reading"]]
    assert len(billed_readings) == 1
    assert billed_readings[0]["reading_value"] == 1120


def test_normal_readings_same_day_are_not_merged(client, auth_headers):
    _enable_feature(auth_headers, client)
    meter = _create_meter(client, auth_headers, "Meter A")
    meter_id = meter["id"]

    client.post(
        f"/api/v1/electricity/meters/{meter_id}/readings",
        json={"reading_value": 1000, "reading_date": "2026-08-01"},
        headers=auth_headers,
    )
    client.post(
        f"/api/v1/electricity/meters/{meter_id}/readings",
        json={"reading_value": 1005, "reading_date": "2026-08-01"},
        headers=auth_headers,
    )

    readings = client.get(
        f"/api/v1/electricity/meters/{meter_id}/readings", headers=auth_headers
    ).json()
    assert len(readings) == 2


def test_shared_user_can_view_and_log_readings_on_a_shared_meter(client, auth_headers):
    _enable_feature(auth_headers, client)
    meter = _create_meter(client, auth_headers, "Shared Meter")

    other_email = f"shared-{uuid.uuid4()}@example.com"
    other_headers = _register_and_get_headers(client, other_email)
    _enable_feature(other_headers, client)

    # Not shared yet — the other user can't see or touch it.
    before = client.get("/api/v1/electricity/meters", headers=other_headers)
    assert before.json() == []
    denied_reading = client.post(
        f"/api/v1/electricity/meters/{meter['id']}/readings",
        json={"reading_value": 100, "reading_date": "2026-08-01"},
        headers=other_headers,
    )
    assert denied_reading.status_code == 404

    share = client.post(
        f"/api/v1/electricity/meters/{meter['id']}/share",
        json={"email": other_email},
        headers=auth_headers,
    )
    assert share.status_code == 200, share.text
    assert share.json()["shared_with"] == [other_email]

    # Now visible to the other user, marked as not theirs, and writable —
    # but they don't see who else has access (that's owner-only info).
    other_list = client.get("/api/v1/electricity/meters", headers=other_headers).json()
    assert [m["id"] for m in other_list] == [meter["id"]]
    assert other_list[0]["is_owner"] is False
    assert other_list[0]["shared_with"] == []

    reading = client.post(
        f"/api/v1/electricity/meters/{meter['id']}/readings",
        json={"reading_value": 500, "reading_date": "2026-08-01"},
        headers=other_headers,
    )
    assert reading.status_code == 200

    # The owner sees the shared user's reading too, via insights.
    owner_insights = client.get("/api/v1/electricity/insights", headers=auth_headers).json()
    assert owner_insights["meters"][0]["last_reading"]["reading_value"] == 500
    assert owner_insights["meters"][0]["is_owner"] is True
    assert owner_insights["meters"][0]["shared_with"] == [other_email]


def test_only_the_owner_can_share_a_meter(client, auth_headers):
    _enable_feature(auth_headers, client)
    meter = _create_meter(client, auth_headers, "Meter A")

    other_email = f"nonowner-{uuid.uuid4()}@example.com"
    other_headers = _register_and_get_headers(client, other_email)
    _enable_feature(other_headers, client)

    # A non-owner gets the same 404 as a nonexistent meter would — sharing
    # never reveals whether a meter id it doesn't own exists at all.
    forbidden = client.post(
        f"/api/v1/electricity/meters/{meter['id']}/share",
        json={"email": other_email},
        headers=other_headers,
    )
    assert forbidden.status_code == 404

    no_such_user = client.post(
        f"/api/v1/electricity/meters/{meter['id']}/share",
        json={"email": "nobody-registered@example.com"},
        headers=auth_headers,
    )
    assert no_such_user.status_code == 404
