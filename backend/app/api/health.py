"""Health check route."""

from fastapi import APIRouter

router = APIRouter(prefix="/api", tags=["system"])


@router.get("/health")
def health() -> dict:
    return {"status": "ok"}
