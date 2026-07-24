import pytest
import asyncio
import httpx
from httpx import AsyncClient

from app.config import settings
from app.services.sandbox.direct import DirectPodDriver
from app.services.sandbox.factory import SandboxDriverFactory

pytestmark = pytest.mark.asyncio

@pytest.fixture(autouse=True)
async def configure_real_k8s_and_ollama():
    # 1. Verify Ollama Health
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            res = await client.get("http://127.0.0.1:11434/api/tags")
            if res.status_code != 200:
                pytest.skip("Local Ollama server is not running on port 11434")
    except Exception as e:
        pytest.skip(f"Local Ollama server unreachable: {e}")

    orig_driver = settings.SANDBOX_DRIVER
    orig_provider = settings.LLM_PROVIDER
    orig_url = settings.LLM_BASE_URL

    # 2. Configure Direct Kubernetes Driver & Ollama Settings
    settings.SANDBOX_DRIVER = "direct"
    settings.LLM_PROVIDER = "ollama"
    settings.LLM_BASE_URL = "http://127.0.0.1:11434"
    settings.SANDBOX_IMAGE = "outpost-sandbox:latest"

    driver = DirectPodDriver()
    try:
        await driver.initialize()
    except Exception as e:
        pytest.skip(f"Rancher Desktop Kubernetes cluster unavailable: {e}")

    SandboxDriverFactory._instance = driver
    SandboxDriverFactory._active_driver_type = "direct"

    yield

    # Restore settings & driver singleton after test
    settings.SANDBOX_DRIVER = orig_driver
    settings.LLM_PROVIDER = orig_provider
    settings.LLM_BASE_URL = orig_url
    SandboxDriverFactory._instance = None
    SandboxDriverFactory._active_driver_type = None

async def test_real_k8s_pod_provisioning_and_ollama_agent_loop(client: AsyncClient):
    # 1. Create Agent with OpenCode Harness against Ollama
    agent_payload = {
        "name": "Real K8s Ollama Coding Agent",
        "model": "gemma4:e2b",
        "harness": "opencode",
        "system": "You are a coding assistant running inside a real Kubernetes Pod.",
        "skills": [{"name": "k8s-skill", "content": "Rancher Desktop k3s guidelines"}],
        "tools": [{"name": "write_file", "description": "Write file to workspace", "input_schema": {}}],
        "environment": {"init_script": "echo 'Real K8s Pod Bootstrapped' > /workspace/k8s_boot.txt"},
        "agent_config": {"auto_execute": True}
    }
    agent_res = await client.post("/v1/agents", json=agent_payload)
    assert agent_res.status_code == 201
    agent_id = agent_res.json()["id"]

    # 2. Create Session (Spawns real Kubernetes pod in agent-sandboxes namespace)
    session_res = await client.post("/v1/sessions", json={"agent_id": agent_id})
    assert session_res.status_code == 201
    session_id = session_res.json()["id"]

    # 3. Post User Event to trigger Agent Turn
    event_res = await client.post(
        f"/v1/sessions/{session_id}/events",
        json={"message": "Please write hello_k8s.txt inside the sandbox workspace."}
    )
    assert event_res.status_code == 202

    # 4. Wait for real pod provisioning & reasoning loop
    status = "running"
    for _ in range(180):
        get_res = await client.get(f"/v1/sessions/{session_id}")
        if get_res.status_code == 200:
            status = get_res.json()["status"]
            if status == "idle":
                break
        await asyncio.sleep(0.5)

    assert status == "idle"

    # 5. Clean up session -> Deletes real Kubernetes pod
    delete_res = await client.delete(f"/v1/sessions/{session_id}")
    assert delete_res.status_code == 204

    # 6. Verify Session record is deleted
    get_deleted = await client.get(f"/v1/sessions/{session_id}")
    assert get_deleted.status_code == 404
