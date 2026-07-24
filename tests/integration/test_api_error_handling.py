import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio

async def test_get_non_existent_agent(client: AsyncClient):
    res = await client.get("/v1/agents/invalid-agent-uuid-000")
    assert res.status_code == 404
    assert "not found" in res.json()["detail"].lower()

async def test_create_session_with_invalid_agent(client: AsyncClient):
    res = await client.post("/v1/sessions", json={"agent_id": "invalid-agent-uuid-000"})
    assert res.status_code == 404
    assert "not found" in res.json()["detail"].lower()

async def test_get_non_existent_session(client: AsyncClient):
    res = await client.get("/v1/sessions/invalid-session-uuid-000")
    assert res.status_code == 404
    assert "not found" in res.json()["detail"].lower()

async def test_post_event_to_non_existent_session(client: AsyncClient):
    res = await client.post(
        "/v1/sessions/invalid-session-uuid-000/events",
        json={"message": "hello"}
    )
    assert res.status_code == 404
    assert "not found" in res.json()["detail"].lower()

async def test_delete_session_lifecycle(client: AsyncClient):
    # 1. Create Agent
    agent_res = await client.post("/v1/agents", json={"name": "Teardown Test Agent"})
    assert agent_res.status_code == 201
    agent_id = agent_res.json()["id"]

    # 2. Create Session
    session_res = await client.post("/v1/sessions", json={"agent_id": agent_id})
    assert session_res.status_code == 201
    session_id = session_res.json()["id"]

    # 3. Delete Session
    delete_res = await client.delete(f"/v1/sessions/{session_id}")
    assert delete_res.status_code == 204

    # 4. Verify Session is gone
    get_res = await client.get(f"/v1/sessions/{session_id}")
    assert get_res.status_code == 404
