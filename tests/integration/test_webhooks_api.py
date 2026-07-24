import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio

async def test_anthropic_webhook_run_started_success(client: AsyncClient):
    payload = {
        "event": "session.status_run_started",
        "session_id": "sess_webhook_test_12345",
        "environment_id": "env_abc123",
        "environment_key": "test_env_secret_key"
    }

    res = await client.post("/webhooks/anthropic", json=payload)
    assert res.status_code == 200
    assert res.json()["status"] == "processing_scheduled"

async def test_anthropic_webhook_missing_env_key(client: AsyncClient):
    payload = {
        "event": "session.status_run_started",
        "session_id": "sess_webhook_test_67890",
        "environment_id": "env_abc123",
        "environment_key": ""
    }

    res = await client.post("/webhooks/anthropic", json=payload)
    assert res.status_code == 400
    assert res.json()["detail"] == "No environment key available"

async def test_anthropic_webhook_ignored_event(client: AsyncClient):
    payload = {
        "event": "session.status_run_completed",
        "session_id": "sess_webhook_test_99999",
        "environment_id": "env_abc123"
    }

    res = await client.post("/webhooks/anthropic", json=payload)
    assert res.status_code == 200
    assert res.json()["status"] == "event_ignored"
