"""Application configuration module.

This module defines the Settings class, which loads and validates
environment variables using Pydantic. Centralizing configuration here
ensures type safety and fail-fast behavior on missing or invalid values.
"""

from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables.

    Attributes:
        environment: The current runtime environment (e.g., "development",
            "production").
        debug: Whether debug mode is enabled.
        api_v1_prefix: URL prefix for version 1 of the API.
        project_name: Human-readable name of the project.
        database_url: Async SQLAlchemy connection string for PostgreSQL.
        redis_url: Connection string for the Redis cache.
        celery_broker_url: Connection string for the Celery message broker.
        celery_result_backend: Connection string for the Celery result backend.
        secret_key: Secret key used to sign JWT tokens.
        algorithm: Algorithm used to sign JWT tokens.
        access_token_expire_minutes: JWT access token expiration time in minutes.
        low_stock_alert_threshold_default: Default stock quantity threshold
            below which a low-stock alert is triggered.
        cors_allowed_origins: Origins allowed to make cross-origin
            requests to the API (e.g. the frontend's URL).
    """

    environment: str = "development"
    debug: bool = True
    api_v1_prefix: str = "/api/v1"
    project_name: str = "Inventory Management API"

    database_url: str
    redis_url: str
    celery_broker_url: str
    celery_result_backend: str

    secret_key: str
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 30

    low_stock_alert_threshold_default: int = 10

    cors_allowed_origins: list[str] = ["http://localhost:3000"]

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    @field_validator("cors_allowed_origins", mode="before")
    @classmethod
    def split_comma_separated_origins(cls, value: str | list[str]) -> str | list[str]:
        """Allow CORS_ALLOWED_ORIGINS to be set as a comma-separated string.

        Environment variables are always strings, and a JSON list is
        awkward to hand-write in a .env file, so a plain comma-separated
        value (e.g. "http://localhost:3000,https://app.example.com") is
        accepted alongside an actual list.

        Args:
            value: The raw value from the environment or a default list.

        Returns:
            str | list[str]: A list of origins, or the original value if
            it was already a list.
        """
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value


@lru_cache
def get_settings() -> Settings:
    """Return a cached instance of the application settings.

    Using lru_cache ensures the .env file is read and validated only
    once per application lifecycle, instead of on every import.

    Returns:
        Settings: The validated application settings instance.
    """
    return Settings()
