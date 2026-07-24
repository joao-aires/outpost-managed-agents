import asyncio
import logging
import httpx
from app.config import settings
from app.services.sandbox.direct import DirectPodDriver
from app.services.sandbox.factory import SandboxDriverFactory
from app.main import app

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("workload_test")

async def get_pod_name_for_session(driver: DirectPodDriver, session_id: str) -> str:
    pod_list = await driver.v1.list_namespaced_pod(
        namespace=driver.namespace,
        label_selector=f"outpost-cma/session-id={session_id}"
    )
    if pod_list.items:
        return pod_list.items[0].metadata.name
    return None

async def run_workload():
    logger.info("=== STEP 1: Setting up Direct Pod Driver & Ollama Settings ===")
    settings.SANDBOX_DRIVER = "direct"
    settings.LLM_PROVIDER = "ollama"
    settings.LLM_BASE_URL = "http://127.0.0.1:11434"
    settings.SANDBOX_IMAGE = "outpost-sandbox:latest"

    driver = DirectPodDriver()
    await driver.initialize()
    SandboxDriverFactory._instance = driver
    SandboxDriverFactory._active_driver_type = "direct"

    # Initialize SQLite Database tables
    from app.database import init_db
    await init_db()

    # Reconcile warm pool to ensure warm pods exist
    logger.info("Reconciling pre-warmed pod pool...")
    await driver.reconcile_warm_pool()

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        
        # --- TEST 1: WARM POD AGENT WORKLOAD ---
        logger.info("\n=== TEST 1: WARM POD AGENT WORKLOAD ===")
        agent_payload = {
            "name": "Enterprise OpenCode Math Agent",
            "model": "gemma4:e2b",
            "harness": "opencode",
            "system": "You are a professional software engineer inside a Kubernetes pod.",
            "skills": [{"name": "math-skill", "content": "Write clean, tested Python code."}],
            "tools": [
                {"name": "write_file", "description": "Write file to workspace", "input_schema": {}},
                {"name": "bash", "description": "Run bash command in sandbox", "input_schema": {}},
                {"name": "read_file", "description": "Read file from workspace", "input_schema": {}}
            ],
            "environment": {
                "init_script": "echo 'WARM POD INITIALIZED' > /workspace/warm_init.txt"
            },
            "agent_config": {"auto_execute": True}
        }

        agent_res = await client.post("/v1/agents", json=agent_payload)
        assert agent_res.status_code == 201, agent_res.text
        agent = agent_res.json()
        agent_id = agent["id"]
        logger.info(f"Created Agent {agent_id} with OpenCode harness.")

        # Create Session -> Should claim a pre-warmed pod
        sess_res = await client.post("/v1/sessions", json={"agent_id": agent_id})
        assert sess_res.status_code == 201, sess_res.text
        session = sess_res.json()
        session_id = session["id"]
        logger.info(f"Created Session {session_id}.")

        # Post coding workload event
        prompt = (
            "Please perform the following workload:\n"
            "1. Write a python file `/workspace/math_utils.py` containing `def factorial(n): return 1 if n <= 1 else n * factorial(n - 1)`.\n"
            "2. Write a test file `/workspace/test_math.py` with `def test_factorial(): assert factorial(5) == 120`.\n"
            "3. Run `python3 -m unittest /workspace/test_math.py` using bash tool and tell me the output."
        )
        event_res = await client.post(f"/v1/sessions/{session_id}/events", json={"message": prompt})
        assert event_res.status_code == 202, event_res.text
        logger.info("Submitted workload event to Agent. Waiting for execution loop...")

        # Wait for execution loop
        for i in range(120):
            s_res = await client.get(f"/v1/sessions/{session_id}")
            st = s_res.json()["status"]
            if i % 10 == 0:
                logger.info(f"Session {session_id} status: {st} (elapsed {i*0.5:.1f}s)")
            if st == "idle":
                break
            await asyncio.sleep(0.5)

        logger.info(f"Session {session_id} finished workload!")
        pod_name = await get_pod_name_for_session(driver, session_id)
        logger.info(f"Session {session_id} mapped to Kubernetes Pod '{pod_name}'.")

        # Verify files inside pod
        if pod_name:
            exec_check = await driver.execute_command(pod_name, "cat /workspace/warm_init.txt; echo '---'; ls -la /workspace")
            logger.info(f"Pod Filesystem Check:\n{exec_check['stdout']}")

        # Cleanup Session 1
        await client.delete(f"/v1/sessions/{session_id}")
        logger.info(f"Cleaned up session {session_id} and deleted pod {pod_name}.")

        # --- TEST 2: COLD POD EXECUTION ---
        logger.info("\n=== TEST 2: COLD POD AGENT WORKLOAD ===")
        sess2_res = await client.post("/v1/sessions", json={"agent_id": agent_id})
        assert sess2_res.status_code == 201, sess2_res.text
        session2 = sess2_res.json()
        session2_id = session2["id"]
        logger.info(f"Created Cold Session {session2_id}.")

        event2_res = await client.post(f"/v1/sessions/{session2_id}/events", json={"message": "Write /workspace/hello_cold.txt with content 'Cold Pod Success'."})
        assert event2_res.status_code == 202

        for i in range(120):
            s_res = await client.get(f"/v1/sessions/{session2_id}")
            st = s_res.json()["status"]
            if st == "idle":
                break
            await asyncio.sleep(0.5)

        logger.info(f"Cold Session {session2_id} finished workload!")
        pod2_name = await get_pod_name_for_session(driver, session2_id)
        logger.info(f"Cold Session {session2_id} mapped to Kubernetes Pod '{pod2_name}'.")

        if pod2_name:
            exec_check2 = await driver.execute_command(pod2_name, "cat /workspace/hello_cold.txt")
            logger.info(f"Cold Pod File Check: {exec_check2['stdout'].strip()}")

        await client.delete(f"/v1/sessions/{session2_id}")
        logger.info(f"Cleaned up session {session2_id} and pod {pod2_name}.")

if __name__ == "__main__":
    asyncio.run(run_workload())
