import asyncio
import time
import logging
import statistics
import httpx
from typing import List, Dict

from app.config import settings
from app.services.sandbox.direct import DirectPodDriver
from app.services.sandbox.factory import SandboxDriverFactory
from app.database import init_db
from app.main import app

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("adr0001_benchmark")

async def measure_session_ttfb(client: httpx.AsyncClient, agent_id: str) -> Dict[str, float]:
    start_time = time.perf_counter()
    res = await client.post("/v1/sessions", json={"agent_id": agent_id})
    ttfb = (time.perf_counter() - start_time) * 1000.0
    
    assert res.status_code == 201, f"Failed session creation: {res.text}"
    session_data = res.json()
    return {
        "ttfb_ms": ttfb,
        "session_id": session_data["id"],
        "pod_name": session_data.get("pod_name", "unknown")
    }

async def benchmark_batch(client: httpx.AsyncClient, agent_id: str, count: int, label: str) -> List[Dict[str, float]]:
    logger.info(f"\n>>> Running Batch: {label} ({count} sessions)...")
    results = []
    session_ids = []
    for i in range(count):
        res = await measure_session_ttfb(client, agent_id)
        results.append(res)
        session_ids.append(res["session_id"])
        logger.info(f"[{label} #{i+1:02d}] TTFB: {res['ttfb_ms']:.2f} ms | Pod: {res['pod_name']}")
    
    # Cleanup sessions
    for sid in session_ids:
        await client.delete(f"/v1/sessions/{sid}")
    return results

def calc_stats(values: List[float]) -> Dict[str, float]:
    sorted_vals = sorted(values)
    n = len(sorted_vals)
    return {
        "min": sorted_vals[0],
        "max": sorted_vals[-1],
        "mean": statistics.mean(sorted_vals),
        "median": statistics.median(sorted_vals),
        "p95": sorted_vals[int(0.95 * n) - 1] if n > 0 else sorted_vals[-1],
    }

async def run_comparison():
    logger.info("=========================================================================")
    logger.info(" Outpost Managed Agents — ADR 0001 Impact Benchmark")
    logger.info(" Evaluating Node Local Cache Enabled (ADR 0001) vs Disabled")
    logger.info("=========================================================================\n")

    settings.SANDBOX_DRIVER = "direct"
    settings.LLM_PROVIDER = "ollama"
    settings.LLM_BASE_URL = "http://127.0.0.1:11434"
    settings.SANDBOX_IMAGE = "outpost-sandbox:latest"

    driver = DirectPodDriver()
    await driver.initialize()
    SandboxDriverFactory._instance = driver
    SandboxDriverFactory._active_driver_type = "direct"
    await init_db()

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        # Create Test Agent
        agent_res = await client.post("/v1/agents", json={
            "name": "ADR 0001 Benchmark Agent",
            "model": "gemma4:e2b",
            "harness": "opencode",
            "system": "Benchmarking ADR 0001 Node Local Cache impact.",
            "skills": [],
            "tools": [],
            "agent_config": {"auto_execute": True}
        })
        agent_id = agent_res.json()["id"]

        # -------------------------------------------------------------
        # TEST 1: WARM PODS — NODE CACHE ENABLED (ADR 0001)
        # -------------------------------------------------------------
        settings.ENABLE_NODE_LOCAL_CACHE = True
        settings.WARM_POOL_SIZE = 10
        await driver.reconcile_warm_pool()
        await asyncio.sleep(3)
        warm_cache_on = await benchmark_batch(client, agent_id, 10, "Warm Pod (Cache ON)")

        # -------------------------------------------------------------
        # TEST 2: WARM PODS — NODE CACHE DISABLED
        # -------------------------------------------------------------
        settings.ENABLE_NODE_LOCAL_CACHE = False
        # Recreate warm pool without hostPath volume mounts
        pod_list = await driver.v1.list_namespaced_pod(namespace=driver.namespace, label_selector="outpost-cma/role=warm-pool")
        for p in pod_list.items:
            try:
                await driver.v1.delete_namespaced_pod(name=p.metadata.name, namespace=driver.namespace, grace_period_seconds=0)
            except Exception:
                pass
        await asyncio.sleep(2)
        await driver.reconcile_warm_pool()
        await asyncio.sleep(3)
        warm_cache_off = await benchmark_batch(client, agent_id, 10, "Warm Pod (Cache OFF)")

        # -------------------------------------------------------------
        # TEST 3: COLD PODS — NODE CACHE ENABLED (ADR 0001)
        # -------------------------------------------------------------
        settings.WARM_POOL_SIZE = 0
        pod_list = await driver.v1.list_namespaced_pod(namespace=driver.namespace, label_selector="outpost-cma/role=warm-pool")
        for p in pod_list.items:
            try:
                await driver.v1.delete_namespaced_pod(name=p.metadata.name, namespace=driver.namespace, grace_period_seconds=0)
            except Exception:
                pass
        await asyncio.sleep(2)
        settings.ENABLE_NODE_LOCAL_CACHE = True
        cold_cache_on = await benchmark_batch(client, agent_id, 10, "Cold Pod (Cache ON)")

        # -------------------------------------------------------------
        # TEST 4: COLD PODS — NODE CACHE DISABLED
        # -------------------------------------------------------------
        settings.ENABLE_NODE_LOCAL_CACHE = False
        cold_cache_off = await benchmark_batch(client, agent_id, 10, "Cold Pod (Cache OFF)")

        # Restore defaults
        settings.ENABLE_NODE_LOCAL_CACHE = True
        settings.WARM_POOL_SIZE = 3
        await driver.reconcile_warm_pool()

    # Statistical Summaries
    w_on = calc_stats([r["ttfb_ms"] for r in warm_cache_on])
    w_off = calc_stats([r["ttfb_ms"] for r in warm_cache_off])
    c_on = calc_stats([r["ttfb_ms"] for r in cold_cache_on])
    c_off = calc_stats([r["ttfb_ms"] for r in cold_cache_off])

    print("\n==========================================================================================")
    print("                 ADR 0001 LOCAL NODE DISK CACHE COMPARATIVE RESULTS                      ")
    print("==========================================================================================")
    print(f"{'Metric':<14} | {'Warm (Cache ON)':<18} | {'Warm (Cache OFF)':<18} | {'Cold (Cache ON)':<18} | {'Cold (Cache OFF)':<18}")
    print("-" * 95)
    print(f"{'Min TTFB':<14} | {w_on['min']:<18.2f} | {w_off['min']:<18.2f} | {c_on['min']:<18.2f} | {c_off['min']:<18.2f}")
    print(f"{'Mean TTFB':<14} | {w_on['mean']:<18.2f} | {w_off['mean']:<18.2f} | {c_on['mean']:<18.2f} | {c_off['mean']:<18.2f}")
    print(f"{'Median TTFB':<14} | {w_on['median']:<18.2f} | {w_off['median']:<18.2f} | {c_on['median']:<18.2f} | {c_off['median']:<18.2f}")
    print(f"{'P95 TTFB':<14} | {w_on['p95']:<18.2f} | {w_off['p95']:<18.2f} | {c_on['p95']:<18.2f} | {c_off['p95']:<18.2f}")
    print(f"{'Max TTFB':<14} | {w_on['max']:<18.2f} | {w_off['max']:<18.2f} | {c_on['max']:<18.2f} | {c_off['max']:<18.2f}")
    print("==========================================================================================")

if __name__ == "__main__":
    asyncio.run(run_comparison())
