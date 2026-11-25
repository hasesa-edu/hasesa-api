import httpx
import pytest

from hasesa_api.main import create_app


@pytest.mark.anyio
async def test_liveness_needs_no_database() -> None:
    transport = httpx.ASGITransport(app=create_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.get("/v1/health")
    assert res.status_code == 200
    assert res.json() == {"status": "ok"}


@pytest.mark.anyio
async def test_openapi_schema_is_served() -> None:
    transport = httpx.ASGITransport(app=create_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.get("/v1/openapi.json")
    assert res.status_code == 200
    assert "/v1/health" in res.json()["paths"]
