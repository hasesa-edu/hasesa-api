import pytest

from hasesa_api.db import to_asyncpg_url


def test_neon_url_becomes_asyncpg_with_tls() -> None:
    url, ssl = to_asyncpg_url(
        "postgresql://u:p@ep-x-pooler.eu-central-1.aws.neon.tech/neondb?sslmode=require&channel_binding=require"
    )
    assert url == "postgresql+asyncpg://u:p@ep-x-pooler.eu-central-1.aws.neon.tech/neondb"
    assert ssl is True


def test_local_url_without_sslmode_has_no_tls() -> None:
    url, ssl = to_asyncpg_url("postgres://u:p@localhost:5432/hasesa")
    assert url == "postgresql+asyncpg://u:p@localhost:5432/hasesa"
    assert ssl is False


def test_other_query_params_are_kept() -> None:
    url, _ = to_asyncpg_url("postgresql://u:p@h/db?sslmode=disable&application_name=api")
    assert url.endswith("/db?application_name=api")


def test_rejects_non_postgres_urls() -> None:
    with pytest.raises(ValueError):
        to_asyncpg_url("mysql://u:p@h/db")
