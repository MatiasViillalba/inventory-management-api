"""Password hashing and JWT token utilities.

Centralizing these here keeps bcrypt and PyJWT usage out of the
service and API layers, which should only depend on the functions
below rather than on the underlying crypto libraries.
"""

from datetime import datetime, timedelta, timezone
from typing import Any

import jwt
from passlib.context import CryptContext

from app.core.config import get_settings

settings = get_settings()

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    """Hash a plaintext password for storage.

    Args:
        password: The plaintext password to hash.

    Returns:
        str: The bcrypt hash to persist on the User model.
    """
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Check a plaintext password against a stored hash.

    Args:
        plain_password: The password submitted by the user.
        hashed_password: The hash stored on the User model.

    Returns:
        bool: True if the password matches the hash.
    """
    return pwd_context.verify(plain_password, hashed_password)


def create_access_token(subject: str, expires_delta: timedelta | None = None) -> str:
    """Create a signed JWT access token.

    Args:
        subject: The value to embed as the token's "sub" claim,
            typically the user's id.
        expires_delta: Optional custom expiration window; defaults to
            settings.access_token_expire_minutes.

    Returns:
        str: The encoded JWT.
    """
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(minutes=settings.access_token_expire_minutes)
    )
    payload: dict[str, Any] = {"sub": subject, "exp": expire}
    return jwt.encode(payload, settings.secret_key, algorithm=settings.algorithm)


def decode_access_token(token: str) -> dict[str, Any]:
    """Decode and verify a JWT access token.

    Args:
        token: The encoded JWT to verify.

    Returns:
        dict[str, Any]: The decoded token payload.

    Raises:
        jwt.PyJWTError: If the token is expired, malformed, or has an
            invalid signature.
    """
    return jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])
