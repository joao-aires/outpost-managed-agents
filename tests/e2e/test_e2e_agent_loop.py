import pytest
import asyncio
import time
from httpx import AsyncClient

from tests.e2e.local_llm_server import LocalLLMServer
from app.config import settings
from app.services.orchestrator import agent_orchestrator

pytestmark = pytest.mark.asyncio

@pytest.fixture(autouse=True)
def run_local_llm_server():
    server = LocalLLMServer()
    server.start()
    time.sleep(0.3)  # Allow server thread to start
    
    server_url = f"http://127.0.0.1:{server.port}"
    settings.LLM_BASE_URL = server_url
    agent_orchestrator.client = agent_orchestrator.client.__class__(
        api_key="local-llm-key",
        base_url=server_url
    )
    yield
    server.stop()

async def test_e2e_agent_harness_execution_loop(client: AsyncClient):
    # 1. Create Agent with OpenCode Harness & Skills
    agent_payload = {
        "name": "E2E OpenCode Coding Agent",
        "model": "qwen2.5-coder",
        "harness": "opencode",
        "system": "You are an E2E autonomous code generator.",
        "skills": [{"name": "fastapi-skill", "content": "FastAPI rules"}],
        "tools": [{"name": "write_file", "description": "Write file", "input_schema": {}}],
        "environment": {"init_script": "echo 'E2E Init Executed'"},
        "agent_config": {"interpreter": "python3"}
    }
    agent_res = await client.post("/v1/agents", json=agent_payload)
    assert agent_res.status_code == 201
    agent_data = agent_res.json()
    agent_id = agent_data["id"]
    assert agent_data["harness"] == "opencode"

    # 2. Create Session
    session_res = await client.post("/v1/sessions", json={"agent_id": agent_id})
    assert session_res.status_code == 201
    session_id = session_res.json()["id"]

    # 3. Post User Event to trigger Agent Reasoning Loop
    event_res = await client.post(
        f"/v1/sessions/{session_id}/events",
        json={"message": "Please write the E2E verification file."}
    )
    assert event_res.status_code == 202

    # 4. Wait for background agent loop to complete turn
    status = "running"
    for _ in range(50):
        get_session_res = await client.get(f"/v1/sessions/{session_id}")
        if get_session_res.status_code == 200:
            status = get_session_res.json()["status"]
            if status == "idle":
                break
        await asyncio.sleep(0.1)

    # 5. Verify Session Status returned to 'idle'
    assert status == "idle"

    # 6. Verify Session Details & Completion
    get_session_res = await client.get(f"/v1/sessions/{session_id}")
    assert get_session_res.status_code == 200
    assert get_session_res.json()["status"] == "idle"
