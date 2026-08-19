"""Aggregates all v1 API routers under a single APIRouter.

New resource routers (warehouses, products, inventory, etc.) are
included here as they are added in later commits, keeping app/main.py
free of per-endpoint wiring.
"""

from fastapi import APIRouter

from app.api.v1.endpoints import health, warehouses

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(warehouses.router)
