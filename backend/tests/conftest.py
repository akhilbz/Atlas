"""
Test infrastructure.

Each test runs inside a transaction that is rolled back on teardown, so tests
are fully isolated without truncating tables between runs.  The test database
(atlas_test on port 5433) must be running — start it with:

    docker-compose up -d db_test
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.config import get_settings
from app.database import Base, get_db
from app.main import app

# ---------------------------------------------------------------------------
# Engine scoped to the test session — tables are created once and torn down
# at the end.
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def test_engine():
    """Create all tables in the test DB at session start; drop them at the end."""
    engine = create_engine(get_settings().test_database_url)
    # pgvector extension must exist before create_all attempts to create the
    # vector(1536) column on the chunks table.
    with engine.connect() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        conn.commit()
    Base.metadata.create_all(engine)
    yield engine
    Base.metadata.drop_all(engine)


# ---------------------------------------------------------------------------
# Per-test DB session wrapped in a transaction that is rolled back afterward.
# ---------------------------------------------------------------------------

@pytest.fixture()
def db(test_engine):
    """Yield a Session in a savepoint so rollback always works, even after an IntegrityError."""
    connection = test_engine.connect()
    transaction = connection.begin()
    # Nested savepoint means the route can call rollback() on IntegrityError without
    # invalidating the outer transaction we rely on for test isolation.
    connection.begin_nested()
    TestingSession = sessionmaker(bind=connection, autocommit=False, autoflush=False)
    session = TestingSession()

    yield session

    session.close()
    transaction.rollback()
    connection.close()


# ---------------------------------------------------------------------------
# TestClient with the get_db dependency overridden to use the test session.
# ---------------------------------------------------------------------------

@pytest.fixture()
def client(db):
    """Return a synchronous TestClient with the test DB wired in."""
    app.dependency_overrides[get_db] = lambda: db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Convenience fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def registered_user(client):
    """Create a user via the API and return the response JSON."""
    resp = client.post(
        "/api/auth/signup",
        json={"email": "test@example.com", "password": "password123"},
    )
    assert resp.status_code == 201
    return resp.json()


@pytest.fixture()
def auth_headers(client):
    """Return Authorization headers for a freshly created + logged-in user."""
    client.post(
        "/api/auth/signup",
        json={"email": "auth@example.com", "password": "password123"},
    )
    resp = client.post(
        "/api/auth/login",
        json={"email": "auth@example.com", "password": "password123"},
    )
    assert resp.status_code == 200
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def refresh_token(client):
    """Return a valid refresh token for a freshly created user."""
    client.post(
        "/api/auth/signup",
        json={"email": "refresh@example.com", "password": "password123"},
    )
    resp = client.post(
        "/api/auth/login",
        json={"email": "refresh@example.com", "password": "password123"},
    )
    assert resp.status_code == 200
    return resp.json()["refresh_token"]
