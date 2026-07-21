def test_register(client):
    response = client.post(
        "/api/v1/auth/register",
        json={"email": "test@example.com", "password": "supersecret123"},
    )
    assert response.status_code == 200

    body = response.json()
    assert "access_token" in body
    assert body["token_type"] == "bearer"


def test_register_duplicate_email_rejected(client):
    client.post(
        "/api/v1/auth/register",
        json={"email": "dupe@example.com", "password": "supersecret123"},
    )
    response = client.post(
        "/api/v1/auth/register",
        json={"email": "dupe@example.com", "password": "differentpass1"},
    )
    assert response.status_code == 400   

def test_me_returns_current_user(client):
    register_response = client.post(
        "/api/v1/auth/register",
        json={"email": "me-test@example.com", "password": "supersecret123"},
    )
    token = register_response.json()["access_token"]

    response = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    assert response.json()["email"] == "me-test@example.com"    