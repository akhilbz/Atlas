"""
Auth route tests.

Coverage:
  signup  — success, duplicate email, short password, invalid email, missing fields
  login   — success, wrong password, unknown email, missing fields
  refresh — success, access token rejected, invalid token, expired token
  /me     — valid token, no token, expired token, malformed token
"""

import uuid
from datetime import datetime, timedelta, timezone

from jose import jwt

from app.config import get_settings


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_expired_token(token_type: str, user_id: str | None = None) -> str:
    """Return a structurally valid JWT that expired one minute ago."""
    settings = get_settings()
    payload = {
        "sub": user_id or str(uuid.uuid4()),
        "type": token_type,
        "exp": datetime.now(timezone.utc) - timedelta(minutes=1),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


# ---------------------------------------------------------------------------
# Signup
# ---------------------------------------------------------------------------

def test_signup_success(client):
    resp = client.post("/api/auth/signup", json={"email": "new@example.com", "password": "securepass"})
    assert resp.status_code == 201
    body = resp.json()
    assert body["email"] == "new@example.com"
    assert "id" in body
    assert "created_at" in body
    # Password must never be returned
    assert "password" not in body
    assert "hashed_password" not in body


def test_signup_duplicate_email(client, registered_user):
    resp = client.post(
        "/api/auth/signup",
        json={"email": "test@example.com", "password": "anotherpass"},
    )
    assert resp.status_code == 409
    assert "already exists" in resp.json()["detail"].lower()


def test_signup_short_password(client):
    resp = client.post("/api/auth/signup", json={"email": "short@example.com", "password": "abc"})
    assert resp.status_code == 422


def test_signup_invalid_email(client):
    resp = client.post("/api/auth/signup", json={"email": "not-an-email", "password": "password123"})
    assert resp.status_code == 422


def test_signup_missing_password(client):
    resp = client.post("/api/auth/signup", json={"email": "missing@example.com"})
    assert resp.status_code == 422


def test_signup_missing_email(client):
    resp = client.post("/api/auth/signup", json={"password": "password123"})
    assert resp.status_code == 422


def test_signup_empty_body(client):
    resp = client.post("/api/auth/signup", json={})
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Login
# ---------------------------------------------------------------------------

def test_login_success(client, registered_user):
    resp = client.post(
        "/api/auth/login",
        json={"email": "test@example.com", "password": "password123"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "access_token" in body
    assert "refresh_token" in body
    assert body["token_type"] == "bearer"
    # Tokens must be non-empty strings
    assert isinstance(body["access_token"], str) and len(body["access_token"]) > 0
    assert isinstance(body["refresh_token"], str) and len(body["refresh_token"]) > 0


def test_login_wrong_password(client, registered_user):
    resp = client.post(
        "/api/auth/login",
        json={"email": "test@example.com", "password": "wrongpassword"},
    )
    assert resp.status_code == 401


def test_login_unknown_email(client):
    resp = client.post(
        "/api/auth/login",
        json={"email": "nobody@example.com", "password": "password123"},
    )
    assert resp.status_code == 401


def test_login_missing_password(client, registered_user):
    resp = client.post("/api/auth/login", json={"email": "test@example.com"})
    assert resp.status_code == 422


def test_login_empty_body(client):
    resp = client.post("/api/auth/login", json={})
    assert resp.status_code == 422


def test_login_wrong_and_correct_password_same_error(client, registered_user):
    """Wrong password and unknown email must return the same 401 to prevent email enumeration."""
    wrong_pw = client.post(
        "/api/auth/login",
        json={"email": "test@example.com", "password": "wrongpassword"},
    )
    unknown = client.post(
        "/api/auth/login",
        json={"email": "nobody@example.com", "password": "password123"},
    )
    assert wrong_pw.status_code == unknown.status_code == 401
    assert wrong_pw.json()["detail"] == unknown.json()["detail"]


# ---------------------------------------------------------------------------
# Refresh
# ---------------------------------------------------------------------------

def test_refresh_success(client, refresh_token):
    resp = client.post("/api/auth/refresh", json={"refresh_token": refresh_token})
    assert resp.status_code == 200
    body = resp.json()
    assert "access_token" in body
    assert body["token_type"] == "bearer"
    assert "refresh_token" not in body  # refresh endpoint must NOT re-issue a refresh token


def test_refresh_with_access_token_is_rejected(client, auth_headers):
    """Sending an access token to /refresh must fail — wrong token type."""
    access_token = auth_headers["Authorization"].split(" ")[1]
    resp = client.post("/api/auth/refresh", json={"refresh_token": access_token})
    assert resp.status_code == 401


def test_refresh_invalid_token(client):
    resp = client.post("/api/auth/refresh", json={"refresh_token": "this.is.garbage"})
    assert resp.status_code == 401


def test_refresh_expired_token(client):
    expired = _make_expired_token("refresh")
    resp = client.post("/api/auth/refresh", json={"refresh_token": expired})
    assert resp.status_code == 401


def test_refresh_missing_token(client):
    resp = client.post("/api/auth/refresh", json={})
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Protected route (/me) — verifies get_current_user dependency
# ---------------------------------------------------------------------------

def test_me_with_valid_token(client, auth_headers):
    resp = client.get("/api/auth/me", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["email"] == "auth@example.com"
    assert "hashed_password" not in body


def test_me_without_token(client):
    resp = client.get("/api/auth/me")
    assert resp.status_code == 403  # HTTPBearer returns 403 when no credentials supplied


def test_me_with_malformed_token(client):
    resp = client.get("/api/auth/me", headers={"Authorization": "Bearer not.a.real.token"})
    assert resp.status_code == 401


def test_me_with_expired_access_token(client, registered_user):
    expired = _make_expired_token("access", user_id=registered_user["id"])
    resp = client.get("/api/auth/me", headers={"Authorization": f"Bearer {expired}"})
    assert resp.status_code == 401


def test_me_with_refresh_token_rejected(client, refresh_token):
    """A refresh token must not be accepted on protected endpoints (wrong type)."""
    resp = client.get("/api/auth/me", headers={"Authorization": f"Bearer {refresh_token}"})
    assert resp.status_code == 401


def test_me_with_nonexistent_user_token(client):
    """A valid JWT for a user_id that doesn't exist in the DB must return 401."""
    settings = get_settings()
    token = jwt.encode(
        {
            "sub": str(uuid.uuid4()),
            "email": "ghost@example.com",
            "type": "access",
            "exp": datetime.now(timezone.utc) + timedelta(minutes=30),
        },
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )
    resp = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 401


def test_me_with_jwt_missing_type_claim_rejected(client, registered_user):
    """A correctly signed JWT with no 'type' field must be rejected — not treated as access token."""
    settings = get_settings()
    token = jwt.encode(
        {
            "sub": registered_user["id"],
            "exp": datetime.now(timezone.utc) + timedelta(minutes=30),
            # intentionally no "type" key
        },
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )
    resp = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 401
