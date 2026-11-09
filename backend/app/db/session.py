"""
Database Session Management

Provides async SQLAlchemy session configuration and dependency injection.

Supports:
    - SQLite (development) with StaticPool
    - PostgreSQL (production) with connection pooling
"""

import os
from pathlib import Path
from typing import AsyncGenerator
from uuid import uuid4

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool, StaticPool

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


def postgres_connect_args() -> dict:
    """asyncpg options compatible with Supabase/PgBouncer transaction pooling."""
    return {
        "statement_cache_size": 0,
        "prepared_statement_cache_size": 0,
        "prepared_statement_name_func": lambda: f"__asyncpg_{uuid4()}__",
        "timeout": settings.DATABASE_CONNECT_TIMEOUT_SECONDS,
        "command_timeout": settings.DATABASE_COMMAND_TIMEOUT_SECONDS,
    }

# Ensure data directory exists for SQLite
if settings.is_sqlite:
    data_dir = Path("./data")
    data_dir.mkdir(parents=True, exist_ok=True)

# Convert sqlite URL to async version if needed
database_url = settings.DATABASE_URL
if database_url.startswith("sqlite:///"):
    database_url = database_url.replace("sqlite:///", "sqlite+aiosqlite:///")

# Build engine kwargs based on database type
engine_kwargs: dict = {
    "echo": settings.DATABASE_ECHO,
}

if settings.is_sqlite:
    engine_kwargs.update({
        "connect_args": {"check_same_thread": False},
        "poolclass": StaticPool,
    })
elif os.getenv("VERCEL"):
    # Serverless instances must not each retain a large local connection pool.
    # Supabase/PgBouncer performs the shared transaction pooling.
    engine_kwargs.update({
        "poolclass": NullPool,
        "connect_args": postgres_connect_args(),
    })
else:
    engine_kwargs.update({
        "pool_size": settings.DATABASE_POOL_SIZE,
        "max_overflow": settings.DATABASE_MAX_OVERFLOW,
        "pool_pre_ping": True,
        "pool_recycle": 300,
        "connect_args": postgres_connect_args(),
    })

# Create async engine
engine = create_async_engine(database_url, **engine_kwargs)

# Create async session factory
async_session_factory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    Dependency that provides a database session.
    
    Usage:
        @router.get("/items")
        async def get_items(db: AsyncSession = Depends(get_db)):
            ...
    """
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def init_db() -> None:
    """Initialize the database (create tables)."""
    from app.db.base import Base
    from app.models import (  # noqa: F401 - Import models to register them
        user,
        location,
        category,
        item,
        stock,
        transaction,
        transfer,
        asset,
        attachment,
        notification,
        audit,
        employee_record,
        generated_document,
    )
    
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    
    logger.info("Database tables created successfully")
