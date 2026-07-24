import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio

async def test_create_agent_with_harness(client: AsyncClient):
    payload = {
        "name": "OpenCode Autonomous Agent",
        "model": "qwen2.5-coder",
        "harness": "opencode",
        "system": "You are a coding interpreter bot.",
        "skills": [{"name": "fastapi-dev", "content": "FastAPI best practices"}],
        "tools": [{"name": "bash", "description": "Run shell", "input_schema": {}}],
        "environment": {"init_script": "pip install fastapi"},
        "agent_config": {"auto_execute": True}
    }
    
    res = await client.post("/v1/agents", json=payload)
    assert res.status_code == 201
    data = res.json()
    assert data["harness"] == "opencode"
    assert data["model"] == "qwen2.5-coder"
    assert len(data["skills"]) == 1
    assert data["environment"]["init_script"] == "pip install fastapi"
    
    agent_id = data["id"]
    get_res = await client.get(f"/v1/agents/{agent_id}")
    assert get_res.status_code == 200
    assert get_res.json()["harness"] == "opencode"
