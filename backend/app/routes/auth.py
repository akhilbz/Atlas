import structlog
from fastapi import APIRouter, HTTPException, status
from sqlalchemy.exc import IntegrityError

from app.models.user import User
from app.schemas.user import AccessToken, Token, TokenRefresh, UserCreate, UserResponse
from app.services.auth import (
    CurrentUserDep,
    DbDep,
    create_access_token,
    create_refresh_token,
    decode_refresh_token,
    hash_password,
    verify_password,
)

logger = structlog.get_logger()

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/signup", status_code=status.HTTP_201_CREATED)
def signup(payload: UserCreate, db: DbDep) -> UserResponse:
    """Create a new user account. Returns the public user profile."""
    user = User(email=payload.email, hashed_password=hash_password(payload.password))
    db.add(user)
    try:
        db.commit()
        db.refresh(user)
    except IntegrityError:
        db.rollback()
        logger.warning("signup_duplicate_email", email=payload.email)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email already exists",
        )

    logger.info("user_created", user_id=str(user.id), email=user.email)
    return UserResponse.model_validate(user)


@router.post("/login")
def login(payload: UserCreate, db: DbDep) -> Token:
    """Authenticate with email + password. Returns access and refresh tokens."""
    user = db.query(User).filter(User.email == payload.email).first()

    if user is None or not verify_password(payload.password, user.hashed_password):
        logger.warning("login_failed", email=payload.email)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    access_token = create_access_token(user.id, user.email)
    refresh_token = create_refresh_token(user.id)
    logger.info("user_logged_in", user_id=str(user.id))
    return Token(access_token=access_token, refresh_token=refresh_token)


@router.post("/refresh")
def refresh(payload: TokenRefresh, db: DbDep) -> AccessToken:
    """Exchange a valid refresh token for a new access token."""
    user_id = decode_refresh_token(payload.refresh_token)

    user = db.get(User, user_id)
    if user is None:
        logger.warning("refresh_user_not_found", user_id=str(user_id))
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    access_token = create_access_token(user.id, user.email)
    logger.info("token_refreshed", user_id=str(user.id))
    return AccessToken(access_token=access_token)


@router.get("/me")
def me(current_user: CurrentUserDep) -> UserResponse:
    """Return the authenticated user's profile. Used to verify access tokens in tests."""
    return UserResponse.model_validate(current_user)
