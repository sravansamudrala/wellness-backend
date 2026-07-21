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

    updated = client.put(
        "/api/v1/water/settings",
        json={"daily_goal_ml": 3000},
        headers=auth_headers,
    )
    assert updated.status_code == 200
    assert updated.json()["daily_goal_ml"] == 3000