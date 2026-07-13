import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio

async def test_read_root(client: AsyncClient):
    response = await client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert "project" in data

async def test_agent_lifecycle(client: AsyncClient):
    # 1. Create Agent
    agent_payload = {
        "name": "Test DevOps Agent",
        "model": "claude-3-5-sonnet-latest",
        "system": "You are a DevOps test bot.",
        "tools": []
    }
    create_response = await client.post("/v1/agents", json=agent_payload)
    assert create_response.status_code == 201
    agent_data = create_response.json()
    assert agent_data["name"] == "Test DevOps Agent"
    assert "id" in agent_data
    agent_id = agent_data["id"]

    # 2. Get Agent Details
    get_response = await client.get(f"/v1/agents/{agent_id}")
    assert get_response.status_code == 200
    assert get_response.json()["name"] == "Test DevOps Agent"

    # 3. List Agents
    list_response = await client.get("/v1/agents")
    assert list_response.status_code == 200
    agents = list_response.json()
    assert len(agents) >= 1
    assert any(a["id"] == agent_id for a in agents)

async def test_session_lifecycle(client: AsyncClient):
    # 1. Create Agent first
    agent_payload = {
        "name": "Test Session Agent",
        "model": "claude-3-5-sonnet-latest",
        "system": "You are a session assistant.",
        "tools": []
    }
    agent_res = await client.post("/v1/agents", json=agent_payload)
    agent_id = agent_res.json()["id"]

    # 2. Create Session
    session_payload = {
        "agent_id": agent_id
    }
    create_response = await client.post("/v1/sessions", json=session_payload)
    assert create_response.status_code == 201
    session_data = create_response.json()
    assert "id" in session_data
    assert session_data["status"] == "idle"
    session_id = session_data["id"]

    # 3. Get Session Details
    get_response = await client.get(f"/v1/sessions/{session_id}")
    assert get_response.status_code == 200
    assert get_response.json()["status"] == "idle"
