"""Application-wide domain exceptions.

These exceptions represent business-rule and data-access failures that
are independent of any web framework. API-layer exception handlers
(added in a later commit) translate them into HTTP responses, keeping
the service and repository layers decoupled from FastAPI.
"""


class AppException(Exception):
    """Base class for all application-specific exceptions."""

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


class NotFoundError(AppException):
    """Raised when a requested resource does not exist."""


class ConflictError(AppException):
    """Raised when an operation conflicts with the current resource state."""


class ValidationError(AppException):
    """Raised when domain-level validation of input data fails."""


class InsufficientStockError(AppException):
    """Raised when an inventory operation would result in negative stock."""


class InactiveResourceError(AppException):
    """Raised when an operation targets a soft-deleted or inactive resource."""
