"""Health check endpoint.

Used by orchestrators (Docker, Kubernetes) and uptime monitors to
verify the API is running and can reach its database.
"""

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.session import get_db

router = APIRouter()


@router.get("/health", tags=["Health"])
async def health_check(db: AsyncSession = Depends(get_db)) -> dict[str, str]:
    """Report API and database health.

    Returns:
        dict[str, str]: Status of the API and its database connection.
    """
    await db.execute(text("SELECT 1"))
    return {"status": "ok", "database": "connected"}
