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


def test_register_with_username(client):
    response = client.post(
        "/api/v1/auth/register",
        json={
            "email": "withusername@example.com",
            "password": "supersecret123",
            "username": "coolUser1",
        },
    )
    assert response.status_code == 200


def test_register_duplicate_username_rejected(client):
    client.post(
        "/api/v1/auth/register",
        json={
            "email": "userone@example.com",
            "password": "supersecret123",
            "username": "sharedname",
        },
    )
    response = client.post(
        "/api/v1/auth/register",
        json={
            "email": "usertwo@example.com",
            "password": "supersecret123",
            "username": "SharedName",  # case-insensitive collision
        },
    )
    assert response.status_code == 400


def test_login_by_email(client):
    client.post(
        "/api/v1/auth/register",
        json={"email": "loginemail@example.com", "password": "supersecret123"},
    )
    response = client.post(
        "/api/v1/auth/login",
        json={"identifier": "loginemail@example.com", "password": "supersecret123"},
    )
    assert response.status_code == 200


def test_login_by_username(client):
    client.post(
        "/api/v1/auth/register",
        json={
            "email": "loginusername@example.com",
            "password": "supersecret123",
            "username": "loginname",
        },
    )
    response = client.post(
        "/api/v1/auth/login",
        json={"identifier": "LoginName", "password": "supersecret123"},
    )
    assert response.status_code == 200


def test_update_me_sets_username_and_email(client, auth_headers):
    response = client.patch(
        "/api/v1/auth/me",
        json={"username": "newname", "email": "updated-email@example.com"},
        headers=auth_headers,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["username"] == "newname"
    assert body["email"] == "updated-email@example.com"

    login_response = client.post(
        "/api/v1/auth/login",
        json={"identifier": "newname", "password": "supersecret123"},
    )
    assert login_response.status_code == 200


def test_update_me_rejects_taken_username(client, auth_headers):
    client.post(
        "/api/v1/auth/register",
        json={
            "email": "taken-username-owner@example.com",
            "password": "supersecret123",
            "username": "alreadytaken",
        },
    )
    response = client.patch(
        "/api/v1/auth/me",
        json={"username": "alreadytaken"},
        headers=auth_headers,
    )
    assert response.status_code == 400


def test_update_me_rejects_taken_email(client, auth_headers):
    client.post(
        "/api/v1/auth/register",
        json={
            "email": "taken-email-owner@example.com",
            "password": "supersecret123",
        },
    )
    response = client.patch(
        "/api/v1/auth/me",
        json={"email": "taken-email-owner@example.com"},
        headers=auth_headers,
    )
    assert response.status_code == 400