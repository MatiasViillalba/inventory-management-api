"""Reusable OpenAPI response documentation for domain error paths.

FastAPI only infers a route's documented responses from its
`response_model` (the success path) and, for request bodies, an
automatic 422 for Pydantic validation failures. The 404/409 responses
produced by app.core.error_handlers whenever a service raises
NotFoundError/ConflictError/InsufficientStockError are real, common
outcomes of calling this API, but FastAPI has no way to know about them
on its own — they only exist because a route's docstring says so under
"Raises:". Each endpoint module attaches the subset of the dicts below
that matches its own docstring, via `responses={**NOT_FOUND, **CONFLICT}`,
so Swagger UI/ReDoc document those outcomes with the same
`{"detail": ...}` shape they actually return.
"""

from app.schemas.common import ErrorResponse

NOT_FOUND: dict[int | str, dict] = {
    404: {
        "model": ErrorResponse,
        "description": "The requested resource does not exist.",
    },
}

CONFLICT: dict[int | str, dict] = {
    409: {
        "model": ErrorResponse,
        "description": "The request conflicts with the current state of the resource "
        "(e.g. a duplicate unique field, or an already-resolved alert).",
    },
}

INSUFFICIENT_STOCK: dict[int | str, dict] = {
    409: {
        "model": ErrorResponse,
        "description": "The requested stock movement would reduce a warehouse's "
        "quantity below zero.",
    },
}
