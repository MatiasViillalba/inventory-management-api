"""Shared pytest fixtures for the entire test suite.

This module wires up three layers of test infrastructure, from the
bottom up:

1. A dedicated test database engine/session, isolated per test via a
   transaction that is always rolled back — even when the code under
   test calls `session.commit()` itself (see `db_session`).
2. Reusable domain fixtures (`test_user`, `test_warehouse`,
   `test_product`) that persist minimal valid rows for tests that need
   pre-existing data instead of building it by hand.
3. An HTTP `client` fixture for integration tests, which overrides the
   app's `get_db` dependency so API requests run inside the same
   transaction as the test's own setup/assertions.

The test database is a separate Postgres database (the same server as
`DATABASE_URL`, with a `_test` suffix), not SQLite: the models use
Postgres-specific column types (e.g. `UUID`), so an in-memory SQLite
engine would validate a different set of constraints than production.
"""

from collections.abc import AsyncGenerator
from decimal import Decimal

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.api.deps import get_db
from app.core.base import Base
from app.core.cache import get_redis
from app.core.config import get_settings
from app.core.security import create_access_token, hash_password
from app.main import app
from app.models.product import Product
from app.models.user import User
from app.models.warehouse import Warehouse

settings = get_settings()


def _build_test_database_url() -> str:
    """Derive the test database URL from `settings.database_url`.

    Appends a `_test` suffix to the configured database name so tests
    run against an isolated database on the same Postgres server,
    instead of the development database.

    Returns:
        str: The async connection string for the test database.
    """
    base_url, _, database_name = settings.database_url.rpartition("/")
    return f"{base_url}/{database_name}_test"


test_engine: AsyncEngine = create_async_engine(
    _build_test_database_url(),
    poolclass=NullPool,
)


@pytest_asyncio.fixture(scope="session", autouse=True, loop_scope="session")
async def _test_schema() -> AsyncGenerator[None, None]:
    """Create every table once for the test session and drop them afterward.

    Session-scoped so the (relatively expensive) DDL only runs once per
    test run rather than once per test; per-test isolation is handled
    separately by `db_session`'s transaction rollback.

    Yields:
        None. Control returns to the test session once the schema
        exists, and resumes here at the end of the run to tear it down.
    """
    async with test_engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    yield
    async with test_engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)
    await test_engine.dispose()


@pytest_asyncio.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    """Yield an AsyncSession scoped to a single rolled-back transaction.

    The session is bound to one connection with `join_transaction_mode
    ="create_savepoint"`, so a `session.commit()` performed by the code
    under test (the service layer commits its own transactions) only
    releases a SAVEPOINT instead of ending the outer transaction. The
    outer transaction is rolled back once the test finishes, so no test
    can leak rows into the next one regardless of how the code under
    test manages its own commits.

    Yields:
        AsyncSession: A transactional session for a single test.
    """
    async with test_engine.connect() as connection:
        transaction = await connection.begin()
        session = AsyncSession(
            bind=connection,
            expire_on_commit=False,
            autoflush=False,
            join_transaction_mode="create_savepoint",
        )
        try:
            yield session
        finally:
            await session.close()
            await transaction.rollback()


@pytest_asyncio.fixture
async def client(db_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    """Yield an httpx AsyncClient wired to the app via ASGI transport.

    Overrides the `get_db` dependency so every request handled during
    the test reuses `db_session`'s transaction, keeping API-level
    assertions and direct ORM setup/assertions consistent within the
    same rolled-back transaction. Uses ASGITransport instead of a real
    server, so no socket is opened and the app's `lifespan` (scheduler,
    Redis pub/sub relay) never starts.

    Also overrides `get_redis` with a connection opened fresh for this
    test instead of reusing app.core.cache's process-wide connection
    pool: that pool's internal asyncio locks bind to whichever event
    loop first uses it, and pytest-asyncio gives each test function its
    own loop, so reusing the real pool across tests raises "Event loop
    is closed" the moment a second test touches a Redis-backed route
    (e.g. the cached /reports endpoints).

    Args:
        db_session: The transactional session to inject in place of
            the real `get_db` dependency.

    Yields:
        AsyncClient: An httpx client that can call the app's routes.
    """

    async def _override_get_db() -> AsyncGenerator[AsyncSession, None]:
        yield db_session

    async def _override_get_redis() -> AsyncGenerator[Redis, None]:
        async with Redis.from_url(settings.redis_url, decode_responses=True) as redis_client:
            yield redis_client

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_redis] = _override_get_redis
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as async_client:
        yield async_client
    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def test_user(db_session: AsyncSession) -> User:
    """Persist and return a standard active, non-superuser account.

    Args:
        db_session: The test's transactional session.

    Returns:
        User: The persisted user, with `id` populated.
    """
    user = User(
        email="test.user@example.com",
        hashed_password=hash_password("Sup3rSecret!23"),
        full_name="Test User",
        is_active=True,
        is_superuser=False,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest_asyncio.fixture
async def test_superuser(db_session: AsyncSession) -> User:
    """Persist and return an active superuser account.

    Args:
        db_session: The test's transactional session.

    Returns:
        User: The persisted superuser, with `id` populated.
    """
    user = User(
        email="test.admin@example.com",
        hashed_password=hash_password("Sup3rSecret!23"),
        full_name="Test Admin",
        is_active=True,
        is_superuser=True,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest.fixture
def auth_headers(test_user: User) -> dict[str, str]:
    """Build an Authorization header carrying a valid token for `test_user`.

    Args:
        test_user: The account the token authenticates as.

    Returns:
        dict[str, str]: A header mapping ready to pass to the test client.
    """
    token = create_access_token(subject=str(test_user.id))
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture
async def test_warehouse(db_session: AsyncSession) -> Warehouse:
    """Persist and return a minimal active warehouse.

    Args:
        db_session: The test's transactional session.

    Returns:
        Warehouse: The persisted warehouse, with `id` populated.
    """
    warehouse = Warehouse(
        name="Main Warehouse",
        code="MAIN",
        address="123 Test Street",
        is_active=True,
    )
    db_session.add(warehouse)
    await db_session.commit()
    await db_session.refresh(warehouse)
    return warehouse


@pytest_asyncio.fixture
async def test_product(db_session: AsyncSession) -> Product:
    """Persist and return a minimal active product.

    Args:
        db_session: The test's transactional session.

    Returns:
        Product: The persisted product, with `id` populated.
    """
    product = Product(
        sku="SKU-0001",
        name="Test Product",
        description="A product created for automated tests.",
        price=Decimal("19.99"),
        is_active=True,
    )
    db_session.add(product)
    await db_session.commit()
    await db_session.refresh(product)
    return product
