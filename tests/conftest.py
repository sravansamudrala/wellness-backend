import os

os.environ["DATABASE_URL"] = "postgresql+psycopg://test:test@localhost:5433/wellness_test"
os.environ["JWT_SECRET"] = "test-secret-not-for-real-use"

import pytest
from fastapi.testclient import TestClient
from app.main import app


@pytest.fixture
def client():
    return TestClient(app)


from app.database.base import Base
from app.database.session import engine
from app import models  # noqa: F401 — importing registers every model on Base.metadata


@pytest.fixture(scope="session", autouse=True)
def create_test_tables():
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)

import uuid


@pytest.fixture
def auth_headers(client):
    unique_email = f"fixture-user-{uuid.uuid4()}@example.com"
    response = client.post(
        "/api/v1/auth/register",
        json={"email": unique_email, "password": "supersecret123"},
    )
    token = response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}