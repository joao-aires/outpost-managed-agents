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
logger = logging.getLogger("load_test_benchmark")

async def measure_session_startup_ttfb(client: httpx.AsyncClient, agent_id: str) -> Dict[str, float]:
    """
    Measures Time To First Byte (TTFB) for session creation endpoint.
    """
    start_time = time.perf_counter()
    res = await client.post("/v1/sessions", json={"agent_id": agent_id})
    ttfb = (time.perf_counter() - start_time) * 1000.0  # Convert to milliseconds
    
    assert res.status_code == 201, f"Failed session creation: {res.text}"
    session_data = res.json()
    return {
        "ttfb_ms": ttfb,
        "session_id": session_data["id"],
        "pod_name": session_data.get("pod_name", "unknown")
    }

async def run_benchmark():
    logger.info("=========================================================")
    logger.info(" Outpost Managed Agents — TTFB Load Test Benchmark")
    logger.info(" Target: 10 Warm Pod Sessions vs 10 Cold Pod Sessions")
    logger.info("=========================================================\n")

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
        # 1. Create Test Agent
        agent_res = await client.post("/v1/agents", json={
            "name": "TTFB Benchmark Agent",
            "model": "gemma4:e2b",
            "harness": "opencode",
            "system": "You are a benchmark target.",
            "skills": [],
            "tools": [],
            "agent_config": {"auto_execute": True}
        })
        assert agent_res.status_code == 201
        agent_id = agent_res.json()["id"]

        # =========================================================
        # BENCHMARK PART A: 10 WARM POD SESSIONS
        # =========================================================
        logger.info("--- Preparing Pre-Warmed Pod Pool (10 Warm Pods) ---")
        settings.WARM_POOL_SIZE = 10
        await driver.reconcile_warm_pool()
        
        # Wait for 10 warm pods to be ready in k8s
        for _ in range(30):
            pod_list = await driver.v1.list_namespaced_pod(
                namespace=driver.namespace,
                label_selector="outpost-cma/role=warm-pool"
            )
            ready = [p for p in pod_list.items if p.status.phase == "Running" and not p.metadata.deletion_timestamp]
            if len(ready) >= 10:
                logger.info(f"Warm Pool Ready: {len(ready)} pods online.")
                break
            await asyncio.sleep(1)

        logger.info("\n>>> Starting Benchmark: 10 Warm Pod Sessions...")
        warm_results: List[Dict[str, float]] = []
        warm_session_ids = []

        for i in range(10):
            res = await measure_session_startup_ttfb(client, agent_id)
            warm_results.append(res)
            warm_session_ids.append(res["session_id"])
            logger.info(f"[Warm Pod #{i+1:02d}] TTFB: {res['ttfb_ms']:.2f} ms | Pod: {res['pod_name']}")

        # Clean up warm sessions
        for sid in warm_session_ids:
            await client.delete(f"/v1/sessions/{sid}")

        # =========================================================
        # BENCHMARK PART B: 10 COLD POD SESSIONS
        # =========================================================
        logger.info("\n--- Draining Warm Pool for Cold Pod Benchmark ---")
        settings.WARM_POOL_SIZE = 0
        # Delete any remaining warm pool pods
        pod_list = await driver.v1.list_namespaced_pod(
            namespace=driver.namespace,
            label_selector="outpost-cma/role=warm-pool"
        )
        for p in pod_list.items:
            try:
                await driver.v1.delete_namespaced_pod(name=p.metadata.name, namespace=driver.namespace, grace_period_seconds=0)
            except Exception:
                pass

        await asyncio.sleep(2)

        logger.info("\n>>> Starting Benchmark: 10 Cold Pod Sessions (On-Demand Pod Creation)...")
        cold_results: List[Dict[str, float]] = []
        cold_session_ids = []

        for i in range(10):
            res = await measure_session_startup_ttfb(client, agent_id)
            cold_results.append(res)
            cold_session_ids.append(res["session_id"])
            logger.info(f"[Cold Pod #{i+1:02d}] TTFB: {res['ttfb_ms']:.2f} ms | Pod: {res['pod_name']}")

        # Clean up cold sessions
        for sid in cold_session_ids:
            await client.delete(f"/v1/sessions/{sid}")

        # Restore default warm pool size
        settings.WARM_POOL_SIZE = 3
        await driver.reconcile_warm_pool()

    # =========================================================
    # STATISTICAL ANALYSIS & REPORTING
    # =========================================================
    warm_ttfbs = [r["ttfb_ms"] for r in warm_results]
    cold_ttfbs = [r["ttfb_ms"] for r in cold_results]

    def calc_stats(values: List[float]) -> Dict[str, float]:
        sorted_vals = sorted(values)
        n = len(sorted_vals)
        return {
            "min": sorted_vals[0],
            "max": sorted_vals[-1],
            "mean": statistics.mean(sorted_vals),
            "median": statistics.median(sorted_vals),
            "p95": sorted_vals[int(0.95 * n) - 1] if n > 0 else sorted_vals[-1],
            "p99": sorted_vals[int(0.99 * n) - 1] if n > 0 else sorted_vals[-1]
        }

    warm_stats = calc_stats(warm_ttfbs)
    cold_stats = calc_stats(cold_ttfbs)

    speedup = cold_stats["mean"] / warm_stats["mean"] if warm_stats["mean"] > 0 else 0

    print("\n=========================================================================")
    print("                    LOAD TEST BENCHMARK RESULTS                          ")
    print("=========================================================================")
    print(f"{'Metric':<18} | {'Warm Pod (ms)':<16} | {'Cold Pod (ms)':<16} | {'Speedup':<10}")
    print("-" * 70)
    print(f"{'Min TTFB':<18} | {warm_stats['min']:<16.2f} | {cold_stats['min']:<16.2f} | {cold_stats['min']/warm_stats['min']:.1f}x")
    print(f"{'Mean TTFB':<18} | {warm_stats['mean']:<16.2f} | {cold_stats['mean']:<16.2f} | {speedup:.1f}x")
    print(f"{'Median TTFB':<18} | {warm_stats['median']:<16.2f} | {cold_stats['median']:<16.2f} | {cold_stats['median']/warm_stats['median']:.1f}x")
    print(f"{'P95 TTFB':<18} | {warm_stats['p95']:<16.2f} | {cold_stats['p95']:<16.2f} | {cold_stats['p95']/warm_stats['p95']:.1f}x")
    print(f"{'P99 TTFB':<18} | {warm_stats['p99']:<16.2f} | {cold_stats['p99']:<16.2f} | {cold_stats['p99']/warm_stats['p99']:.1f}x")
    print(f"{'Max TTFB':<18} | {warm_stats['max']:<16.2f} | {cold_stats['max']:<16.2f} | {cold_stats['max']/warm_stats['max']:.1f}x")
    print("=========================================================================")

if __name__ == "__main__":
    asyncio.run(run_benchmark())
