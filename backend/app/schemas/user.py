import uuid
from datetime import datetime

from pydantic import BaseModel, EmailStr, field_validator


class UserCreate(BaseModel):
    """Payload for creating a new user account."""

    email: EmailStr
    password: str

    @field_validator("password")
    @classmethod
    def password_min_length(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("password must be at least 8 characters")
        return v


class UserResponse(BaseModel):
    """Public user representation — never includes the hashed password."""

    id: uuid.UUID
    email: str
    created_at: datetime

    model_config = {"from_attributes": True}


class Token(BaseModel):
    """Returned on successful login."""

    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class TokenRefresh(BaseModel):
    """Payload for the /refresh endpoint."""

    refresh_token: str


class AccessToken(BaseModel):
    """Returned by the /refresh endpoint."""

    access_token: str
    token_type: str = "bearer"
