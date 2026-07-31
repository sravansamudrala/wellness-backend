import secrets
from datetime import datetime, timedelta
from urllib.parse import parse_qs, urlparse

import jwt
import pytest

from app.core.config import settings
from app.core.security import hash_reset_token
from app.database.session import SessionLocal
from app.models.password_reset_token import PasswordResetToken
from app.models.user import User
from app.services import auth_service


@pytest.fixture(autouse=True)
def stub_email(monkeypatch):
    sent = []
    monkeypatch.setattr(
        auth_service.email_service,
        "send_password_reset_email",
        lambda to, reset_link: sent.append((to, reset_link)),
    )
    return sent


def _extract_token(reset_link):
    return parse_qs(urlparse(reset_link).query)["token"][0]


def test_forgot_password_existing_email_sends_reset_email(client, stub_email):
    client.post(
        "/api/v1/auth/register",
        json={"email": "reset-user@example.com", "password": "supersecret123"},
    )

    response = client.post(
        "/api/v1/auth/forgot-password",
        json={"email": "reset-user@example.com"},
    )

    assert response.status_code == 200
    assert len(stub_email) == 1
    assert stub_email[0][0] == "reset-user@example.com"


def test_forgot_password_nonexistent_email_returns_same_generic_message(client, stub_email):
    client.post(
        "/api/v1/auth/register",
        json={"email": "reset-user2@example.com", "password": "supersecret123"},
    )
    real_response = client.post(
        "/api/v1/auth/forgot-password",
        json={"email": "reset-user2@example.com"},
    )
    stub_email.clear()

    fake_response = client.post(
        "/api/v1/auth/forgot-password",
        json={"email": "no-such-user@example.com"},
    )

    assert fake_response.status_code == 200
    assert fake_response.json()["message"] == real_response.json()["message"]
    assert len(stub_email) == 0


def test_reset_password_with_valid_token_succeeds(client, stub_email):
    client.post(
        "/api/v1/auth/register",
        json={"email": "reset-user3@example.com", "password": "oldpassword1"},
    )
    client.post(
        "/api/v1/auth/forgot-password",
        json={"email": "reset-user3@example.com"},
    )
    token = _extract_token(stub_email[0][1])

    response = client.post(
        "/api/v1/auth/reset-password",
        json={"token": token, "new_password": "newpassword1"},
    )

    assert response.status_code == 200


def test_old_password_rejected_new_password_works_after_reset(client, stub_email):
    client.post(
        "/api/v1/auth/register",
        json={"email": "reset-user4@example.com", "password": "oldpassword1"},
    )
    client.post(
        "/api/v1/auth/forgot-password",
        json={"email": "reset-user4@example.com"},
    )
    token = _extract_token(stub_email[0][1])
    client.post(
        "/api/v1/auth/reset-password",
        json={"token": token, "new_password": "newpassword1"},
    )

    old_login = client.post(
        "/api/v1/auth/login",
        json={"identifier": "reset-user4@example.com", "password": "oldpassword1"},
    )
    new_login = client.post(
        "/api/v1/auth/login",
        json={"identifier": "reset-user4@example.com", "password": "newpassword1"},
    )

    assert old_login.status_code == 401
    assert new_login.status_code == 200


def test_reset_password_token_cannot_be_reused(client, stub_email):
    client.post(
        "/api/v1/auth/register",
        json={"email": "reset-user5@example.com", "password": "oldpassword1"},
    )
    client.post(
        "/api/v1/auth/forgot-password",
        json={"email": "reset-user5@example.com"},
    )
    token = _extract_token(stub_email[0][1])
    client.post(
        "/api/v1/auth/reset-password",
        json={"token": token, "new_password": "newpassword1"},
    )

    response = client.post(
        "/api/v1/auth/reset-password",
        json={"token": token, "new_password": "anotherpassword1"},
    )

    assert response.status_code == 400


def test_reset_password_expired_token_rejected(client):
    register_response = client.post(
        "/api/v1/auth/register",
        json={"email": "reset-user6@example.com", "password": "oldpassword1"},
    )
    token = register_response.json()["access_token"]
    me_response = client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"}
    )
    user_id = me_response.json()["id"]

    raw_token = secrets.token_urlsafe(32)
    db = SessionLocal()
    try:
        db.add(
            PasswordResetToken(
                user_id=user_id,
                token_hash=hash_reset_token(raw_token),
                expires_at=datetime.utcnow() - timedelta(minutes=1),
            )
        )
        db.commit()
    finally:
        db.close()

    response = client.post(
        "/api/v1/auth/reset-password",
        json={"token": raw_token, "new_password": "newpassword1"},
    )

    assert response.status_code == 400


def test_reset_password_garbage_token_rejected(client):
    response = client.post(
        "/api/v1/auth/reset-password",
        json={"token": "not-a-real-token", "new_password": "newpassword1"},
    )

    assert response.status_code == 400


def test_old_session_invalidated_after_password_reset(client, stub_email):
    register_response = client.post(
        "/api/v1/auth/register",
        json={"email": "reset-user7@example.com", "password": "oldpassword1"},
    )
    old_token = register_response.json()["access_token"]

    # The old token works before the reset.
    pre_reset = client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {old_token}"}
    )
    assert pre_reset.status_code == 200

    client.post(
        "/api/v1/auth/forgot-password",
        json={"email": "reset-user7@example.com"},
    )
    reset_token = _extract_token(stub_email[0][1])
    client.post(
        "/api/v1/auth/reset-password",
        json={"token": reset_token, "new_password": "newpassword1"},
    )

    post_reset = client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {old_token}"}
    )
    assert post_reset.status_code == 401


def test_fresh_login_works_after_password_reset(client, stub_email):
    client.post(
        "/api/v1/auth/register",
        json={"email": "reset-user8@example.com", "password": "oldpassword1"},
    )
    client.post(
        "/api/v1/auth/forgot-password",
        json={"email": "reset-user8@example.com"},
    )
    reset_token = _extract_token(stub_email[0][1])
    client.post(
        "/api/v1/auth/reset-password",
        json={"token": reset_token, "new_password": "newpassword1"},
    )

    login_response = client.post(
        "/api/v1/auth/login",
        json={"identifier": "reset-user8@example.com", "password": "newpassword1"},
    )
    new_token = login_response.json()["access_token"]

    me_response = client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {new_token}"}
    )
    assert me_response.status_code == 200


def test_token_missing_ver_claim_still_authenticates(client):
    """Backward-compat: tokens minted before this feature shipped have no
    `ver` claim at all. get_current_user must default that to 0 and still
    authenticate a freshly registered (token_version=0) user."""
    client.post(
        "/api/v1/auth/register",
        json={"email": "reset-user9@example.com", "password": "supersecret123"},
    )

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == "reset-user9@example.com").first()
        assert user.token_version == 0
        legacy_token = jwt.encode(
            {"sub": str(user.id), "exp": datetime.utcnow() + timedelta(minutes=5)},
            settings.jwt_secret,
            algorithm=settings.jwt_algorithm,
        )
    finally:
        db.close()

    response = client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {legacy_token}"}
    )
    assert response.status_code == 200