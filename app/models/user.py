"""User model.

Represents an account that can authenticate against the API. Movement
records reference users via their id to track who performed each
stock change.
"""

from sqlalchemy import Boolean, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import BaseModel


class User(BaseModel):
    """An authenticated account.

    Attributes:
        email: Unique login identifier.
        hashed_password: Bcrypt hash of the user's password, never the
            plaintext value.
        full_name: Display name for the user.
        is_active: Whether the account can currently authenticate.
        is_superuser: Whether the account has unrestricted access.
    """

    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str] = mapped_column(String(255), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_superuser: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
