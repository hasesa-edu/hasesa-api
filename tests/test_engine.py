import pytest
from sqlalchemy.pool import NullPool

from hasesa_api import config, db


@pytest.fixture
def fresh_engine(monkeypatch: pytest.MonkeyPatch):
    """Build the engine from the current environment, then reset the caches."""
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@ep-x-pooler.example.neon.tech/db?sslmode=require")

    def build():
        config.get_settings.cache_clear()
        db.get_engine.cache_clear()
        return db.get_engine()

    yield build
    config.get_settings.cache_clear()
    db.get_engine.cache_clear()


def test_null_pool_on_serverless(monkeypatch: pytest.MonkeyPatch, fresh_engine) -> None:
    monkeypatch.setenv("DB_NULL_POOL", "true")
    assert isinstance(fresh_engine().pool, NullPool)


def test_queue_pool_by_default(fresh_engine) -> None:
    engine = fresh_engine()
    assert not isinstance(engine.pool, NullPool)
    assert engine.pool.size() == 5
