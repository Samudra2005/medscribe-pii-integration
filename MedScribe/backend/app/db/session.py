"""
Async database engine and session factory.
This is the single source of truth for how the app talks to Postgres.
"""
from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings

settings = get_settings()

# echo=False in normal operation; flip to True temporarily for local SQL debugging.
# pool_pre_ping=True: checks a connection is alive before handing it out from the
# pool -- prevents a whole class of "connection was closed by the server" errors
# that otherwise surface as random, hard-to-reproduce 500s in production.
engine = create_async_engine(
    settings.DATABASE_URL_ASYNC,
    echo=False,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    FastAPI dependency that yields a database session per-request and
    guarantees it's closed afterward, even if the request raised an error.
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
