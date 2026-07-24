import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio

async def test_session_lifecycle_with_harness_provisioning(client: AsyncClient):
    # 1. Create Agent with Claude Code Harness & Skill
    agent_payload = {
        "name": "Claude Code Refactor Agent",
        "model": "claude-3-5-sonnet-latest",
        "harness": "claude-code",
        "system": "You are a code refactoring bot.",
        "skills": [{"name": "pytest-guidelines", "content": "Write isolated tests"}],
        "tools": [],
        "environment": {"init_script": "echo 'Setting up refactor environment'"},
        "agent_config": {"auto_approve": True}
    }
    agent_res = await client.post("/v1/agents", json=agent_payload)
    assert agent_res.status_code == 201
    agent_id = agent_res.json()["id"]

    # 2. Create Session
    session_res = await client.post("/v1/sessions", json={"agent_id": agent_id})
    assert session_res.status_code == 201
    session_data = session_res.json()
    session_id = session_data["id"]
    assert session_data["status"] == "idle"

    # 3. Post User Event to Session
    event_res = await client.post(f"/v1/sessions/{session_id}/events", json={"message": "Refactor app/main.py"})
    assert event_res.status_code == 202
    assert event_res.json()["status"] == "event_received"

    # 4. Get Session Details
    get_res = await client.get(f"/v1/sessions/{session_id}")
    assert get_res.status_code == 200
    assert get_res.json()["status"] in ("idle", "running", "provisioning")
