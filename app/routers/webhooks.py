import os
import hmac
import hashlib
import logging
import asyncio
from typing import Optional
from fastapi import APIRouter, Request, HTTPException, Header, BackgroundTasks, status
from pydantic import BaseModel

from app.services.kubernetes import sandbox_client

router = APIRouter(prefix="/webhooks", tags=["webhooks"])
logger = logging.getLogger("outpost_cma.webhooks")

# Secret key for webhook signature validation
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "super_secret_webhook_key")

class WebhookPayload(BaseModel):
    event: str
    session_id: str
    environment_id: str
    environment_key: Optional[str] = None # Key to communicate back to Anthropic

async def verify_signature(request: Request, x_webhook_signature: str = Header(...)):
    """
    Verifies that the webhook signature matches to ensure it came from Anthropic.
    """
    body = await request.body()
    expected_signature = hmac.new(
        WEBHOOK_SECRET.encode("utf-8"),
        body,
        hashlib.sha256
    ).hexdigest()
    
    if not hmac.compare_digest(expected_signature, x_webhook_signature):
        logger.warning("Invalid webhook signature received.")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid signature"
        )

async def run_anthropic_worker_task(session_id: str, environment_id: str, environment_key: str):
    """
    Starts the Pod Sandbox, injects the Anthropic Environment credentials,
    and runs the EnvironmentWorker process inside the Pod to process Anthropic's work queue.
    """
    pod_name = f"agent-sandbox-{session_id[:8]}"
    try:
        logger.info(f"Provisioning sandbox pod {pod_name} for Anthropic session {session_id}...")
        # Create Pod
        actual_pod_name = await sandbox_client.create_sandbox_pod(session_id)
        
        # Inject the Environment key and run the worker command inside the sandbox pod.
        # Anthropic CLI tool client connects to the Anthropic work queue.
        # Run command inside pod: 'export ANTHROPIC_ENVIRONMENT_KEY=... && ant beta:worker run-one'
        cmd = (
            f"export ANTHROPIC_ENVIRONMENT_KEY='{environment_key}' && "
            f"export ANTHROPIC_ENVIRONMENT_ID='{environment_id}' && "
            f"ant beta:worker run-one --workdir /workspace"
        )
        
        logger.info(f"Starting Anthropic worker inside Pod {actual_pod_name}...")
        result = await sandbox_client.execute_command(actual_pod_name, cmd)
        logger.info(f"Anthropic worker execution completed. stdout: {result['stdout']}, exit_code: {result['exit_code']}")
        
    except Exception as e:
        logger.error(f"Error executing Anthropic worker task: {e}")
    finally:
        # Tear down sandbox pod once worker has completed or failed
        logger.info(f"Cleaning up sandbox pod {pod_name}...")
        await sandbox_client.delete_sandbox_pod(pod_name)

@router.post("/anthropic")
async def anthropic_webhook(
    request: Request,
    payload: WebhookPayload,
    background_tasks: BackgroundTasks,
    # Depends(verify_signature) # Uncomment in production to enforce signatures
):
    """
    Webhook endpoint to receive events from Anthropic Managed Agents platform.
    When a run starts, we spin up a Kubernetes sandbox and start the EnvironmentWorker.
    """
    logger.info(f"Received Anthropic webhook event: {payload.event} for session {payload.session_id}")
    
    if payload.event == "session.status_run_started":
        env_key = payload.environment_key or os.getenv("ANTHROPIC_ENVIRONMENT_KEY", "")
        if not env_key:
            logger.error("No environment key available to authenticate worker.")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No environment key available"
            )
            
        # Spawn execution task asynchronously in the background
        background_tasks.add_task(
            run_anthropic_worker_task,
            session_id=payload.session_id,
            environment_id=payload.environment_id,
            environment_key=env_key
        )
        return {"status": "processing_scheduled"}
        
    return {"status": "event_ignored"}
