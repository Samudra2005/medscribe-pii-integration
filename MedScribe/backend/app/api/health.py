"""
Health check endpoints. Separated from business routers because these
are infrastructure-level concerns (used by Docker healthchecks, load
balancers, monitoring) rather than application features.
"""
import redis.asyncio as redis
from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.session import get_db

router = APIRouter(tags=["health"])
settings = get_settings()


@router.get("/health")
async def health_check() -> dict:
    """
    Liveness check -- is the process running at all. Kept deliberately
    cheap (no DB/Redis calls) so it can be polled frequently without load.
    """
    return {"status": "ok", "service": settings.PROJECT_NAME, "environment": settings.ENVIRONMENT}


@router.get("/health/ready")
async def readiness_check(db: AsyncSession = Depends(get_db)) -> dict:
    """
    Readiness check -- is the app ACTUALLY able to serve requests, i.e.
    can it reach Postgres and Redis right now. This is the check that
    should gate "is it safe to route traffic here" in any real deployment.
    """
    checks: dict[str, str] = {}
    overall_ok = True

    # ---- Postgres ----
    try:
        await db.execute(text("SELECT 1"))
        checks["postgres"] = "ok"
    except Exception as exc:
        checks["postgres"] = f"error: {exc}"
        overall_ok = False

    # ---- Redis ----
    redis_client = redis.from_url(settings.REDIS_URL, decode_responses=True)
    try:
        await redis_client.ping()
        checks["redis"] = "ok"
    except Exception as exc:
        checks["redis"] = f"error: {exc}"
        overall_ok = False
    finally:
        await redis_client.aclose()

    return {
        "status": "ok" if overall_ok else "degraded",
        "checks": checks,
    }