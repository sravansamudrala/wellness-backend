import os

os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://test:test@localhost:5433/wellness_test")
os.environ.setdefault("JWT_SECRET", "test-secret-not-for-real-use")

# HARD SAFETY CHECK — this suite creates AND DROPS ALL TABLES on teardown.
# `setdefault` above only protects us if DATABASE_URL isn't already set in the
# environment; if a real DATABASE_URL (e.g. production) was ever exported in
# this shell beforehand, setdefault silently leaves it alone. This check is
# the actual guardrail: refuse to run at all unless the resolved URL is
# unambiguously local. (This is not hypothetical — it's why this check exists.)
_resolved_db_url = os.environ["DATABASE_URL"]
if "localhost" not in _resolved_db_url and "127.0.0.1" not in _resolved_db_url:
    raise RuntimeError(
        f"\n\nREFUSING TO RUN TESTS.\n"
        f"DATABASE_URL does not look like a local database: {_resolved_db_url!r}\n"
        f"This test suite calls Base.metadata.drop_all() on teardown — running it "
        f"against anything but a local test database would destroy real data.\n"
        f"If DATABASE_URL is set in your shell from an earlier `export`, run "
        f"`unset DATABASE_URL` before retrying.\n"
    )

import pytest
from fastapi.testclient import TestClient
from app.core.rate_limit import limiter
limiter.enabled = False
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