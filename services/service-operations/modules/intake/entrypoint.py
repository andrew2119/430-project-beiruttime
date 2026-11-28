"""Register intake routes with current assigned-record authority."""

from fastapi import APIRouter

from . import current_evidence, current_routes


router = APIRouter()
router.include_router(current_routes.router)
router.include_router(current_evidence.router)
