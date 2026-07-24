def test_get_today_creates_entry_with_zero_amount(client, auth_headers):
    response = client.get("/api/v1/water/today", headers=auth_headers)

    assert response.status_code == 200
    assert response.json()["amount_ml"] == 0


def test_add_water_accumulates(client, auth_headers):
    first = client.post(
        "/api/v1/water/today/add",
        json={"amount_ml": 500},
        headers=auth_headers,
    )
    assert first.json()["amount_ml"] == 500

    second = client.post(
        "/api/v1/water/today/add",
        json={"amount_ml": 300},
        headers=auth_headers,
    )
    assert second.json()["amount_ml"] == 800


def test_update_settings_changes_daily_goal(client, auth_headers):
    default = client.get("/api/v1/water/settings", headers=auth_headers)
    assert default.json()["daily_goal_ml"] == 2000
    assert default.json()["reminders_enabled"] is False
    assert default.json()["reminder_start_time"] == "09:00:00"
    assert default.json()["reminder_end_time"] == "21:00:00"

    updated = client.put(
        "/api/v1/water/settings",
        json={
            "daily_goal_ml": 3000,
            "reminders_enabled": False,
            "reminder_start_time": "09:00:00",
            "reminder_end_time": "21:00:00",
        },
        headers=auth_headers,
    )
    assert updated.status_code == 200
    assert updated.json()["daily_goal_ml"] == 3000


def test_update_settings_changes_reminder_window(client, auth_headers):
    updated = client.put(
        "/api/v1/water/settings",
        json={
            "daily_goal_ml": 2000,
            "reminders_enabled": True,
            "reminder_start_time": "07:30:00",
            "reminder_end_time": "22:00:00",
        },
        headers=auth_headers,
    )
    assert updated.status_code == 200
    body = updated.json()
    assert body["reminders_enabled"] is True
    assert body["reminder_start_time"] == "07:30:00"
    assert body["reminder_end_time"] == "22:00:00"

    refetched = client.get("/api/v1/water/settings", headers=auth_headers)
    assert refetched.json()["reminders_enabled"] is True
    assert refetched.json()["reminder_start_time"] == "07:30:00"
    assert refetched.json()["reminder_end_time"] == "22:00:00"