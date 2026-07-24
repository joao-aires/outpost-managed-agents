import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio

async def test_healthz_endpoint(client: AsyncClient):
    res = await client.get("/healthz")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "ok"
    assert data["service"] == "outpost-managed-agents"

async def test_metrics_endpoint(client: AsyncClient):
    res = await client.get("/v1/metrics")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "healthy"
    assert "metrics" in data
    assert "total_agents" in data["metrics"]
    assert "total_sessions" in data["metrics"]
    assert "ready_warm_pods" in data["metrics"]
