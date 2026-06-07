import uuid
from datetime import datetime, timedelta, timezone
from typing import Annotated

import bcrypt as _bcrypt
import structlog
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.models.user import User

logger = structlog.get_logger()

_bearer = HTTPBearer()

TOKEN_TYPE_ACCESS = "access"
TOKEN_TYPE_REFRESH = "refresh"


def hash_password(plain: str) -> str:
    """Return a bcrypt hash of the given plaintext password (12 rounds)."""
    return _bcrypt.hashpw(plain.encode("utf-8"), _bcrypt.gensalt(rounds=12)).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    """Return True if the plaintext matches the bcrypt hash."""
    return _bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))


def create_access_token(user_id: uuid.UUID, email: str) -> str:
    """Return a signed JWT access token valid for JWT_EXPIRATION_MINUTES."""
    settings = get_settings()
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.jwt_expiration_minutes)
    payload = {
        "sub": str(user_id),
        "email": email,
        "type": TOKEN_TYPE_ACCESS,
        "exp": expire,
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def create_refresh_token(user_id: uuid.UUID) -> str:
    """Return a signed JWT refresh token valid for JWT_REFRESH_EXPIRATION_DAYS."""
    settings = get_settings()
    expire = datetime.now(timezone.utc) + timedelta(days=settings.jwt_refresh_expiration_days)
    payload = {
        "sub": str(user_id),
        "type": TOKEN_TYPE_REFRESH,
        "exp": expire,
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def _decode_token(token: str, expected_type: str) -> dict:
    """Decode and validate a JWT. Raises 401 on any failure."""
    settings = get_settings()
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired token",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except JWTError:
        logger.warning("jwt_decode_failed")
        raise credentials_exception

    if payload.get("type") != expected_type:
        logger.warning("jwt_wrong_token_type", expected=expected_type, got=payload.get("type"))
        raise credentials_exception

    if payload.get("sub") is None:
        raise credentials_exception

    return payload


def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(_bearer)],
    db: Annotated[Session, Depends(get_db)],
) -> User:
    """FastAPI dependency — resolves the Bearer token to a User or raises 401."""
    payload = _decode_token(credentials.credentials, TOKEN_TYPE_ACCESS)
    user_id: str = payload["sub"]

    user = db.get(User, uuid.UUID(user_id))
    if user is None:
        logger.warning("jwt_user_not_found", user_id=user_id)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return user


def decode_refresh_token(token: str) -> uuid.UUID:
    """Validate a refresh token and return the user_id it encodes."""
    payload = _decode_token(token, TOKEN_TYPE_REFRESH)
    return uuid.UUID(payload["sub"])


CurrentUserDep = Annotated[User, Depends(get_current_user)]
DbDep = Annotated[Session, Depends(get_db)]
