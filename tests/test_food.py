import uuid


def _entry_payload(**overrides):
    payload = {
        "name": "Banana",
        "quantity": "1 medium",
        "calories": 105,
        "protein_g": 1.3,
        "carbs_g": 27,
        "fat_g": 0.4,
    }
    payload.update(overrides)
    return payload


def test_get_today_starts_empty(client, auth_headers):
    response = client.get("/api/v1/food/today", headers=auth_headers)

    assert response.status_code == 200
    body = response.json()
    assert body["entries"] == []
    assert body["total_calories"] == 0
    assert body["total_protein_g"] == 0
    assert body["total_carbs_g"] == 0
    assert body["total_fat_g"] == 0


def test_create_entry_returns_full_entry(client, auth_headers):
    response = client.post(
        "/api/v1/food", json=_entry_payload(), headers=auth_headers
    )

    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "Banana"
    assert body["quantity"] == "1 medium"
    assert body["calories"] == 105
    assert body["protein_g"] == 1.3
    assert body["carbs_g"] == 27
    assert body["fat_g"] == 0.4
    assert "id" in body
    assert "logged_at" in body


def test_create_entry_allows_omitted_macros(client, auth_headers):
    response = client.post(
        "/api/v1/food",
        json={"name": "Water", "quantity": "1 glass", "calories": 0},
        headers=auth_headers,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["protein_g"] is None
    assert body["carbs_g"] is None
    assert body["fat_g"] is None


def test_get_today_sums_multiple_entries(client, auth_headers):
    client.post("/api/v1/food", json=_entry_payload(name="Banana", calories=105, protein_g=1.3, carbs_g=27, fat_g=0.4), headers=auth_headers)
    client.post(
        "/api/v1/food",
        json={"name": "Toast", "quantity": "2 slices", "calories": 150},
        headers=auth_headers,
    )

    response = client.get("/api/v1/food/today", headers=auth_headers)

    assert response.status_code == 200
    body = response.json()
    assert len(body["entries"]) == 2
    assert body["total_calories"] == 255
    # The second entry omitted macros — they must count as 0, not break the sum.
    assert body["total_protein_g"] == 1.3
    assert body["total_carbs_g"] == 27
    assert body["total_fat_g"] == 0.4


def test_delete_entry_removes_it(client, auth_headers):
    created = client.post(
        "/api/v1/food", json=_entry_payload(), headers=auth_headers
    ).json()

    delete_response = client.delete(
        f"/api/v1/food/{created['id']}", headers=auth_headers
    )
    assert delete_response.status_code == 200
    assert delete_response.json()["ok"] is True

    today = client.get("/api/v1/food/today", headers=auth_headers).json()
    assert today["entries"] == []


def test_delete_nonexistent_entry_returns_404(client, auth_headers):
    response = client.delete(
        f"/api/v1/food/{uuid.uuid4()}", headers=auth_headers
    )
    assert response.status_code == 404


def test_entries_are_scoped_per_user(client, auth_headers):
    other_email = f"fixture-user-{uuid.uuid4()}@example.com"
    other_register = client.post(
        "/api/v1/auth/register",
        json={"email": other_email, "password": "supersecret123"},
    )
    other_headers = {"Authorization": f"Bearer {other_register.json()['access_token']}"}

    created = client.post(
        "/api/v1/food", json=_entry_payload(), headers=auth_headers
    ).json()

    # The other user's "today" must not see the first user's entry...
    other_today = client.get("/api/v1/food/today", headers=other_headers).json()
    assert other_today["entries"] == []

    # ...and can't delete it either (404, not a silent cross-user delete).
    delete_response = client.delete(
        f"/api/v1/food/{created['id']}", headers=other_headers
    )
    assert delete_response.status_code == 404

    # It's still there for the owner.
    owner_today = client.get("/api/v1/food/today", headers=auth_headers).json()
    assert len(owner_today["entries"]) == 1


def test_analyze_photo_without_groq_key_returns_502(client, auth_headers):
    # conftest forces settings.groq_api_key = "" so this never hits real Groq.
    response = client.post(
        "/api/v1/food/analyze-photo",
        headers=auth_headers,
        files={"file": ("meal.jpg", b"not-a-real-image", "image/jpeg")},
    )

    assert response.status_code == 502
    assert "not configured" in response.json()["detail"]


def test_analyze_photo_rejects_non_image_content_type(client, auth_headers):
    response = client.post(
        "/api/v1/food/analyze-photo",
        headers=auth_headers,
        files={"file": ("notes.txt", b"just some text", "text/plain")},
    )

    assert response.status_code == 400