import asyncio
import logging
import base64
import uuid
from typing import Dict, Any
from app.config import settings
from app.services.sandbox.base import BaseSandboxDriver
from app.services.sandbox.direct import DirectPodDriver

logger = logging.getLogger("outpost_cma.sandbox.sigs")

try:
    from kubernetes_asyncio import client
    K8S_AVAILABLE = True
except ImportError:
    K8S_AVAILABLE = False

class SigsSandboxDriver(DirectPodDriver):
    """
    Integrates with kubernetes-sigs/agent-sandbox.
    Submits SandboxClaims to claim/create isolated agent sandboxes,
    then uses direct Pod exec connection once bound.
    """
    def __init__(self):
        super().__init__()
        self.custom_api = None
        self.group = "apps.kubernetes.io"
        self.version = "v1alpha1"
        self.plural = "sandboxclaims"

    async def initialize(self) -> None:
        await super().initialize()
        if K8S_AVAILABLE and self.api_client:
            self.custom_api = client.CustomObjectsApi(self.api_client)

    async def create_sandbox(self, session_id: str) -> str:
        if not self.custom_api:
            raise RuntimeError("Kubernetes custom API client not initialized.")

        claim_name = f"claim-{session_id[:8]}-{uuid.uuid4().hex[:6]}"
        
        # Build SandboxClaim custom object
        claim_manifest = {
            "apiVersion": f"{self.group}/{self.version}",
            "kind": "SandboxClaim",
            "metadata": {
                "name": claim_name,
                "namespace": self.namespace,
                "labels": {
                    "app.kubernetes.io/managed-by": "outpost-cma",
                    "outpost-cma/session-id": session_id
                }
            },
            "spec": {
                "sandboxTemplateRef": {
                    "name": "default-agent-template"
                }
            }
        }

        logger.info(f"Submitting SandboxClaim Custom Object: {claim_name}...")
        await self.custom_api.create_namespaced_custom_object(
            group=self.group,
            version=self.version,
            namespace=self.namespace,
            plural=self.plural,
            body=claim_manifest
        )

        # Wait for the SandboxClaim to be bound to a running Pod
        # Poll status until bound and target pod name is populated in status
        for _ in range(45):
            claim = await self.custom_api.get_namespaced_custom_object(
                group=self.group,
                version=self.version,
                namespace=self.namespace,
                plural=self.plural,
                name=claim_name
            )
            
            status = claim.get("status", {})
            phase = status.get("phase", "")
            pod_name = status.get("podName") or status.get("pod_name") or status.get("boundPodName")
            
            if phase == "Bound" and pod_name:
                logger.info(f"SandboxClaim {claim_name} bound to Pod {pod_name}.")
                return pod_name
            
            await asyncio.sleep(1)

        raise TimeoutError(f"SandboxClaim {claim_name} failed to bind to a running pod in time.")

    async def delete_sandbox(self, sandbox_id: str) -> None:
        # To delete a SIGs sandbox, we delete the SandboxClaim custom object that created it.
        # Find the claim by querying claims matching target pod name or session labels
        if not self.custom_api:
            return

        try:
            # We can list claims labeled with sandbox session ID or match name
            # For robustness, we search by label
            claims = await self.custom_api.list_namespaced_custom_object(
                group=self.group,
                version=self.version,
                namespace=self.namespace,
                plural=self.plural
            )
            
            for item in claims.get("items", []):
                claim_name = item["metadata"]["name"]
                claim_status = item.get("status", {})
                bound_pod = claim_status.get("podName") or claim_status.get("boundPodName")
                
                if bound_pod == sandbox_id or claim_name.endswith(sandbox_id.split("-")[-1]):
                    logger.info(f"Deleting SandboxClaim custom object: {claim_name}...")
                    await self.custom_api.delete_namespaced_custom_object(
                        group=self.group,
                        version=self.version,
                        namespace=self.namespace,
                        plural=self.plural,
                        name=claim_name
                    )
                    return
            
            # If no claim match found, fall back to direct pod deletion
            await super().delete_sandbox(sandbox_id)
        except Exception as e:
            logger.error(f"Error terminating SIGs sandbox claim: {e}")
            await super().delete_sandbox(sandbox_id)

    async def reconcile_warm_pool(self) -> None:
        # Warm pool is handled out-of-band by the SIG-Sandbox CRD Controller in the cluster.
        # This driver does not need to reconcile it directly.
        pass
