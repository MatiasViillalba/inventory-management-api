"""Reusable FastAPI dependencies for database access and authentication.

Centralizes the dependency-injection surface consumed by API endpoint
modules in one place. get_db, get_redis, and get_event_publisher are
re-exported here from app.core.session, app.core.cache, and
app.events.publisher so route modules have a single import source; the
get_current_* dependencies build the authentication/authorization
layer on top of get_db, decoding the caller's JWT and loading the
corresponding User.

These dependencies are not yet wired into any route — endpoints adopt
them by adding e.g. `current_user: User = Depends(get_current_user)`
to a path function's signature as auth requirements are rolled out.
"""

import uuid

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import get_redis
from app.core.config import get_settings
from app.core.exceptions import NotFoundError
from app.core.security import decode_access_token
from app.core.session import get_db
from app.events.publisher import get_event_publisher
from app.models.user import User
from app.repositories.user import UserRepository

__all__ = [
    "get_db",
    "get_redis",
    "get_event_publisher",
    "get_current_user",
    "get_current_active_user",
    "get_current_superuser",
]

_settings = get_settings()

oauth2_scheme = OAuth2PasswordBearer(
    tokenUrl=f"{_settings.api_v1_prefix}/auth/login", auto_error=True
)


async def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Resolve the authenticated User from a bearer JWT.

    Args:
        token: The bearer token extracted from the Authorization header.
        db: Injected async database session.

    Returns:
        User: The account identified by the token's "sub" claim.

    Raises:
        HTTPException: 401 if the token is missing, malformed, expired,
            has an invalid signature, or names a user that no longer
            exists. Deliberately vague to avoid revealing which of
            these applies to an attacker.
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials.",
        headers={"WWW-Authenticate": "Bearer"},
    )

    try:
        payload = decode_access_token(token)
    except jwt.PyJWTError as exc:
        raise credentials_exception from exc

    subject = payload.get("sub")
    if subject is None:
        raise credentials_exception
    try:
        user_id = uuid.UUID(subject)
    except ValueError as exc:
        raise credentials_exception from exc

    try:
        user = await UserRepository(db).get_by_id_or_raise(user_id)
    except NotFoundError as exc:
        raise credentials_exception from exc
    return user


async def get_current_active_user(
    current_user: User = Depends(get_current_user),
) -> User:
    """Require the authenticated user's account to be active.

    Args:
        current_user: The authenticated user, resolved by
            get_current_user.

    Returns:
        User: The same user, once confirmed active.

    Raises:
        HTTPException: 403 if the account has been deactivated.
    """
    if not current_user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Inactive user account."
        )
    return current_user


async def get_current_superuser(
    current_user: User = Depends(get_current_active_user),
) -> User:
    """Require the authenticated user to hold superuser privileges.

    Args:
        current_user: The active authenticated user, resolved by
            get_current_active_user.

    Returns:
        User: The same user, once confirmed a superuser.

    Raises:
        HTTPException: 403 if the account is not a superuser.
    """
    if not current_user.is_superuser:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Superuser privileges required.",
        )
    return current_user
