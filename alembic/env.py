import asyncio
from logging.config import fileConfig

from sqlalchemy.ext.asyncio import create_async_engine

from alembic import context
from hasesa_api.config import get_settings
from hasesa_api.db import to_asyncpg_url
from hasesa_api.models import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _url() -> tuple[str, bool]:
    settings = get_settings()
    # Migrations need a direct connection: the pooler can't hold the
    # session-level locks Alembic uses.
    raw = settings.database_url_direct or settings.database_url
    if not raw:
        raise RuntimeError("Set DATABASE_URL_DIRECT to run migrations")
    return to_asyncpg_url(raw)


def run_migrations_offline() -> None:
    url, _ = _url()
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True, compare_server_default=True)
    with context.begin_transaction():
        context.run_migrations()


def _run(connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata, compare_server_default=True)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    url, ssl = _url()
    engine = create_async_engine(url, connect_args={"ssl": ssl})
    async with engine.connect() as connection:
        await connection.run_sync(_run)
    await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
