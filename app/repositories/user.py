"""Repository for User data access.

Extends BaseRepository with the one query specific to the User
aggregate: lookup by email, the natural key used at login.
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.repositories.base import BaseRepository


class UserRepository(BaseRepository[User]):
    """Data-access layer for User entities.

    Attributes:
        session: The active async database session, inherited from
            BaseRepository.
    """

    def __init__(self, session: AsyncSession) -> None:
        """Initialize the repository bound to the User model.

        Args:
            session: An active AsyncSession injected by the caller.
        """
        super().__init__(User, session)

    async def get_by_email(self, email: str) -> User | None:
        """Fetch a user by their unique login email.

        Args:
            email: The user's email address.

        Returns:
            The matching User, or None if no account has that email.
        """
        statement = select(User).where(User.email == email)
        result = await self.session.execute(statement)
        return result.scalar_one_or_none()

    async def list_active_superusers(self) -> list[User]:
        """List active superuser accounts.

        Used to determine who receives operational notifications, such
        as low-stock alert emails, since the domain has no separate
        notification-recipient concept yet.

        Returns:
            A list of active users with superuser privileges.
        """
        statement = select(User).where(
            User.is_superuser.is_(True), User.is_active.is_(True)
        )
        result = await self.session.execute(statement)
        return list(result.scalars().all())
