import asyncio
import logging
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from daiflow.config import DATABASE_URL

logger = logging.getLogger(__name__)
engine = create_async_engine(DATABASE_URL, echo=False)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def init_db():
    from daiflow.models import Base
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_db():
    """Database session dependency for FastAPI requests.
    
    Handles CancelledError gracefully when requests are interrupted
    (e.g., streaming responses cancelled by client).
    """
    async with async_session() as session:
        try:
            yield session
        except asyncio.CancelledError:
            # Request was cancelled (e.g., client disconnected during streaming)
            # Suppress to prevent ASGI errors during cleanup
            logger.debug("Database session cancelled (client disconnected)")


@asynccontextmanager
async def get_background_db():
    """Create an independent DB session for background tasks.

    Background tasks must NOT use the request-scoped session from get_db()
    because it is closed after the request completes.
    """
    async with async_session() as session:
        try:
            yield session
        except asyncio.CancelledError:
            # Background task was cancelled
            logger.debug("Background DB session cancelled")

# Alias for non-Depends contexts (WebSocket handlers, background tasks)
get_db_session = get_background_db
