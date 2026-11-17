"""Password hashing and JWT issue/verify."""

import hashlib
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

from xenovarients.core.config import get_settings

_hasher = PasswordHasher()


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, InvalidHashError):
        return False


def _now() -> datetime:
    return datetime.now(UTC)


def create_access_token(*, user_id: uuid.UUID, business_id: uuid.UUID | None, role: str) -> str:
    """Short-lived access token. ``business_id`` selects the active tenant."""
    settings = get_settings()
    now = _now()
    claims: dict[str, Any] = {
        "sub": str(user_id),
        "role": role,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=settings.access_token_ttl_minutes)).timestamp()),
        "jti": uuid.uuid4().hex,
        "typ": "access",
    }
    if business_id is not None:
        claims["bid"] = str(business_id)
    return jwt.encode(claims, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> dict[str, Any]:
    """Decode and verify. Raises ``jwt.PyJWTError`` on any problem."""
    settings = get_settings()
    return jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])


def hash_payload(payload: str) -> str:
    """Stable hash of a payload — used for audit before/after hashes (no PII stored)."""
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
