"""
Application lifespan: runs once at startup and once at shutdown.
On startup, we PROVE Postgres and Redis are actually reachable -- not
just "did the app process start" -- so a misconfigured connection fails
loudly at boot, not silently on the first real user request.
"""
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import redis.asyncio as redis
from fastapi import FastAPI
from sqlalchemy import text

from app.core.config import get_settings
from app.core.logging_config import get_logger
from app.db.session import engine

logger = get_logger(__name__)
settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    logger.info("startup_begin", environment=settings.ENVIRONMENT)

    # ---- Verify Postgres ----
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        logger.info("postgres_connection_verified")
    except Exception as exc:
        logger.error("postgres_connection_failed", error=str(exc))
        raise RuntimeError(
            "Could not connect to Postgres at startup. "
            "Check that the medstt_v1_postgres container is running and .env is correct."
        ) from exc

    # ---- Verify Redis ----
    redis_client = redis.from_url(settings.REDIS_URL, decode_responses=True)
    try:
        pong = await redis_client.ping()
        logger.info("redis_connection_verified", pong=pong)
    except Exception as exc:
        logger.error("redis_connection_failed", error=str(exc))
        raise RuntimeError(
            "Could not connect to Redis at startup. "
            "Check that the medstt_v1_redis container is running and .env is correct."
        ) from exc
    finally:
        await redis_client.aclose()

    logger.info("startup_complete")

    yield  # ---- application runs here ----

    logger.info("shutdown_begin")
    await engine.dispose()
    logger.info("shutdown_complete")