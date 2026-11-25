import os

import httpx
import pytest
from sqlalchemy import text

from hasesa_api import config, db
from hasesa_api.identity import google

# Database tests run against a throwaway Postgres (CI starts one, migrated to
# head). Locally they are skipped unless TEST_DATABASE_URL is set; never point
# it at production, because every test empties the tables.
TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL", "")
WEB_SECRET = "test-web-secret"


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def _reset_caches() -> None:
    config.get_settings.cache_clear()
    db.get_engine.cache_clear()
    db.get_sessionmaker.cache_clear()


@pytest.fixture
async def api(monkeypatch: pytest.MonkeyPatch):
    """An HTTP client for the app, backed by the test database, with every table emptied."""
    if not TEST_DATABASE_URL:
        pytest.skip("TEST_DATABASE_URL not set")
    monkeypatch.setenv("DATABASE_URL", TEST_DATABASE_URL)
    monkeypatch.setenv("DB_NULL_POOL", "true")
    monkeypatch.setenv("API_BASE_URL", "http://test")
    monkeypatch.setenv("CLIENT_SECRETS", f"hasesa-web:{WEB_SECRET}")
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "google-web-client")
    _reset_caches()
    async with db.get_engine().begin() as conn:
        await conn.execute(text("TRUNCATE users, auth_sessions, auth_requests, auth_codes CASCADE"))

    from hasesa_api.main import create_app

    transport = httpx.ASGITransport(app=create_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
    await db.get_engine().dispose()
    _reset_caches()


@pytest.fixture
def fake_google(monkeypatch: pytest.MonkeyPatch):
    """Replace Google: the code exchange returns the code itself as the 'ID token',
    and verification turns it into a profile from `profiles`."""
    profiles: dict[str, google.GoogleProfile] = {}

    async def exchange_code(code: str, verifier: str) -> str:
        return code

    async def verify_id_token(id_token: str) -> google.GoogleProfile:
        if id_token == "unverified":
            raise google.UnverifiedEmail("not verified")
        if id_token not in profiles:
            raise google.GoogleError("bad token")
        return profiles[id_token]

    monkeypatch.setattr(google, "exchange_code", exchange_code)
    monkeypatch.setattr(google, "verify_id_token", verify_id_token)
    return profiles
