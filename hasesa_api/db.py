from collections.abc import AsyncIterator
from functools import lru_cache
from typing import Annotated
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from hasesa_api.config import get_settings

# libpq options that asyncpg rejects as keyword arguments. TLS is set through
# connect_args instead.
_LIBPQ_ONLY = {"sslmode", "channel_binding"}


def to_asyncpg_url(url: str) -> tuple[str, bool]:
    """Turn a Neon/libpq URL into an SQLAlchemy asyncpg URL.

    Returns the URL and whether TLS is required. Neon always requires TLS,
    so any sslmode other than "disable" means TLS on.
    """
    parts = urlsplit(url)
    scheme = parts.scheme.split("+", 1)[0]
    if scheme not in ("postgres", "postgresql"):
        raise ValueError("DATABASE_URL must be a postgres:// or postgresql:// URL")
    query = parse_qsl(parts.query, keep_blank_values=True)
    sslmode = dict(query).get("sslmode")
    kept = [(k, v) for k, v in query if k not in _LIBPQ_ONLY]
    ssl = sslmode is not None and sslmode != "disable"
    return urlunsplit(("postgresql+asyncpg", parts.netloc, parts.path, urlencode(kept), "")), ssl


@lru_cache
def get_engine() -> AsyncEngine:
    settings = get_settings()
    if not settings.database_url:
        raise RuntimeError("DATABASE_URL is not set")
    url, ssl = to_asyncpg_url(settings.database_url)
    # Neon's pooler (PgBouncer, transaction mode) can't keep prepared
    # statements across transactions, so turn the statement cache off.
    connect_args = {"ssl": ssl, "statement_cache_size": 0}
    if settings.db_null_pool:
        return create_async_engine(url, poolclass=NullPool, connect_args=connect_args)
    return create_async_engine(
        url,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        pool_pre_ping=True,
        connect_args=connect_args,
    )


@lru_cache
def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(get_engine(), expire_on_commit=False)


async def get_db() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency: one session per request."""
    async with get_sessionmaker()() as session:
        yield session


DbDep = Annotated[AsyncSession, Depends(get_db)]
