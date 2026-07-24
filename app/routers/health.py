import httpx
from typing import Dict, Any
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import func

from app.database import get_db
from app.models.agent import Agent
from app.models.session import Session
from app.config import settings
from app.services.sandbox import sandbox_driver

router = APIRouter(tags=["health"])

@router.get("/healthz")
async def healthz():
    return {"status": "ok", "service": "outpost-managed-agents"}

@router.get("/v1/metrics")
async def get_metrics(db: AsyncSession = Depends(get_db)) -> Dict[str, Any]:
    """
    Enterprise health & operational metrics endpoint.
    Exposes warm pool status, active sessions count, and LLM connection status.
    """
    total_agents = (await db.execute(select(func.count(Agent.id)))).scalar() or 0
    total_sessions = (await db.execute(select(func.count(Session.id)))).scalar() or 0
    running_sessions = (await db.execute(select(func.count(Session.id)).where(Session.status == "running"))).scalar() or 0

    warm_pool_count = 0
    if settings.SANDBOX_DRIVER == "direct" and hasattr(sandbox_driver, "v1") and sandbox_driver.v1:
        try:
            pod_list = await sandbox_driver.v1.list_namespaced_pod(
                namespace=sandbox_driver.namespace,
                label_selector="outpost-cma/role=warm-pool"
            )
            warm_pool_count = len([
                p for p in pod_list.items 
                if p.status.phase == "Running" and not p.metadata.deletion_timestamp
            ])
        except Exception:
            warm_pool_count = -1

    ollama_status = "disabled"
    if settings.LLM_PROVIDER == "ollama":
        try:
            async with httpx.AsyncClient(timeout=2.0) as client:
                res = await client.get(f"{settings.LLM_BASE_URL}/api/tags")
                ollama_status = "healthy" if res.status_code == 200 else "unreachable"
        except Exception:
            ollama_status = "unreachable"

    return {
        "status": "healthy",
        "sandbox_driver": settings.SANDBOX_DRIVER,
        "llm_provider": settings.LLM_PROVIDER,
        "ollama_status": ollama_status,
        "metrics": {
            "total_agents": total_agents,
            "total_sessions": total_sessions,
            "running_sessions": running_sessions,
            "ready_warm_pods": warm_pool_count,
            "target_warm_pool_size": settings.WARM_POOL_SIZE
        }
    }
