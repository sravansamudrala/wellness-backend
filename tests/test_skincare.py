def test_get_today_creates_entry_with_all_false(client, auth_headers):
    response = client.get("/api/v1/skincare/today", headers=auth_headers)

    assert response.status_code == 200
    body = response.json()
    assert body["face_wash"] is False
    assert body["sunscreen"] is False


def test_update_today_sets_booleans(client, auth_headers):
    response = client.put(
        "/api/v1/skincare/today",
        json={
            "face_wash": True,
            "vitamin_c": True,
            "moisturizer": False,
            "sunscreen": True,
            "lipcare": False,
            "cleanser": False,
            "evening_moisturizer": False,
        },
        headers=auth_headers,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["face_wash"] is True
    assert body["moisturizer"] is False
    assert body["sunscreen"] is True