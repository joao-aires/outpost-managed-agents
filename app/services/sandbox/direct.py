import asyncio
import logging
import base64
import uuid
from typing import Dict, Optional
from app.config import settings
from app.services.sandbox.base import BaseSandboxDriver

logger = logging.getLogger("outpost_cma.sandbox.direct")

# Try importing kubernetes dependencies
try:
    from kubernetes_asyncio import client, config
    from kubernetes_asyncio.client.api import core_v1_api
    K8S_AVAILABLE = True
except ImportError:
    K8S_AVAILABLE = False
    logger.warning("kubernetes-asyncio not installed. DirectPodDriver will fail to initialize.")

class DirectPodDriver(BaseSandboxDriver):
    """
    Schedules and manages standard Kubernetes Pods directly.
    """
    def __init__(self):
        self.namespace = settings.KUBERNETES_NAMESPACE
        self.v1 = None
        self.api_client = None

    async def initialize(self) -> None:
        if not K8S_AVAILABLE:
            raise RuntimeError("kubernetes-asyncio library is missing. Cannot use DirectPodDriver.")
            
        try:
            try:
                config.load_incluster_config()
                logger.info("Loaded in-cluster Kubernetes config.")
            except Exception:
                await config.load_kube_config()
                logger.info("Loaded local kubeconfig.")
            
            self.api_client = client.ApiClient()
            self.v1 = core_v1_api.CoreV1Api(self.api_client)
            
            # Ensure Namespace exists
            try:
                await self.v1.read_namespace(self.namespace)
            except client.exceptions.ApiException as e:
                if e.status == 404:
                    ns_spec = client.V1Namespace(metadata=client.V1ObjectMeta(name=self.namespace))
                    await self.v1.create_namespace(body=ns_spec)
                    logger.info(f"Created namespace: {self.namespace}")
                else:
                    raise
        except Exception as e:
            logger.error(f"Failed to initialize Kubernetes API connection: {e}")
            raise

    async def create_sandbox(self, session_id: str) -> str:
        pod_name = f"agent-sandbox-{session_id[:8]}-{uuid.uuid4().hex[:6]}"
        
        # Check warm pool first
        claimed_pod = await self._claim_warm_pod(session_id)
        if claimed_pod:
            return claimed_pod

        # Standard Manifest
        pod_manifest = client.V1Pod(
            metadata=client.V1ObjectMeta(
                name=pod_name,
                labels={
                    "app.kubernetes.io/managed-by": "outpost-cma",
                    "outpost-cma/role": "sandbox",
                    "outpost-cma/session-id": session_id,
                }
            ),
            spec=client.V1PodSpec(
                containers=[
                    client.V1Container(
                        name="sandbox",
                        image=settings.SANDBOX_IMAGE,
                        image_pull_policy="IfNotPresent",
                        command=["tail", "-f", "/dev/null"],
                        resources=client.V1ResourceRequirements(
                            limits={"cpu": "1", "memory": "1Gi"},
                            requests={"cpu": "0.2", "memory": "256Mi"}
                        ),
                        security_context=client.V1SecurityContext(
                            allow_privilege_escalation=False,
                            run_as_user=1000,
                            run_as_group=1000
                        )
                    )
                ],
                restart_policy="Never",
                termination_grace_period_seconds=5
            )
        )

        logger.info(f"Creating sandbox pod {pod_name}...")
        await self.v1.create_namespaced_pod(namespace=self.namespace, body=pod_manifest)

        # Wait for pod running state
        for _ in range(30):
            pod = await self.v1.read_namespaced_pod(name=pod_name, namespace=self.namespace)
            if pod.status.phase == "Running":
                logger.info(f"Pod {pod_name} is running.")
                return pod_name
            await asyncio.sleep(1)

        raise TimeoutError(f"Pod {pod_name} timed out starting.")

    async def execute_command(self, sandbox_id: str, command: str) -> Dict[str, str]:
        try:
            cmd = ["kubectl", "exec", "-n", self.namespace, sandbox_id, "--", "/bin/bash", "-c", command]
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await proc.communicate()
            return {
                "stdout": stdout.decode("utf-8"),
                "stderr": stderr.decode("utf-8"),
                "exit_code": str(proc.returncode)
            }
        except Exception as e:
            logger.error(f"Command execution failed inside pod {sandbox_id}: {e}")
            return {"stdout": "", "stderr": str(e), "exit_code": "1"}

    async def read_file(self, sandbox_id: str, path: str) -> bytes:
        result = await self.execute_command(sandbox_id, f"cat {path} | base64")
        if result["exit_code"] != "0":
            raise FileNotFoundError(f"Failed to read file {path}: {result['stderr']}")
        return base64.b64decode(result["stdout"].strip())

    async def write_file(self, sandbox_id: str, path: str, content: bytes) -> bool:
        b64_content = base64.b64encode(content).decode("utf-8")
        dir_path = "/".join(path.split("/")[:-1])
        if dir_path:
            await self.execute_command(sandbox_id, f"mkdir -p {dir_path}")
            
        cmd = f"echo '{b64_content}' | base64 -d > {path}"
        result = await self.execute_command(sandbox_id, cmd)
        return result["exit_code"] == "0"

    async def delete_sandbox(self, sandbox_id: str) -> None:
        logger.info(f"Deleting sandbox pod {sandbox_id}...")
        try:
            await self.v1.delete_namespaced_pod(
                name=sandbox_id,
                namespace=self.namespace,
                grace_period_seconds=0
            )
        except client.exceptions.ApiException as e:
            if e.status != 404:
                logger.error(f"Failed to delete pod {sandbox_id}: {e}")

    async def reconcile_warm_pool(self) -> None:
        """
        Maintains a pool of pre-warmed sandbox pods for zero-latency agent startup.
        """
        if not self.v1:
            return

        target_pool_size = settings.WARM_POOL_SIZE
        try:
            pod_list = await self.v1.list_namespaced_pod(
                namespace=self.namespace,
                label_selector="outpost-cma/role=warm-pool"
            )
            
            ready_warm_pods = [
                p for p in pod_list.items 
                if p.status.phase == "Running" and not p.metadata.deletion_timestamp
            ]
            
            current_count = len(ready_warm_pods)
            needed = target_pool_size - current_count
            
            if needed > 0:
                logger.info(f"Warm pool reconciler: creating {needed} warm pod(s)...")
                for _ in range(needed):
                    await self._create_warm_pod()
        except Exception as e:
            logger.error(f"Failed to reconcile warm pod pool: {e}")

    async def _create_warm_pod(self) -> str:
        warm_id = uuid.uuid4().hex[:8]
        pod_name = f"agent-sandbox-warm-{warm_id}"
        
        pod_manifest = client.V1Pod(
            metadata=client.V1ObjectMeta(
                name=pod_name,
                labels={
                    "app.kubernetes.io/managed-by": "outpost-cma",
                    "outpost-cma/role": "warm-pool",
                }
            ),
            spec=client.V1PodSpec(
                containers=[
                    client.V1Container(
                        name="sandbox",
                        image=settings.SANDBOX_IMAGE,
                        image_pull_policy="IfNotPresent",
                        command=["tail", "-f", "/dev/null"],
                        resources=client.V1ResourceRequirements(
                            limits={"cpu": "1", "memory": "1Gi"},
                            requests={"cpu": "0.2", "memory": "256Mi"}
                        ),
                        security_context=client.V1SecurityContext(
                            allow_privilege_escalation=False,
                            run_as_user=1000,
                            run_as_group=1000
                        )
                    )
                ],
                restart_policy="Never",
                termination_grace_period_seconds=5
            )
        )

        await self.v1.create_namespaced_pod(namespace=self.namespace, body=pod_manifest)
        return pod_name

    async def _claim_warm_pod(self, session_id: str) -> Optional[str]:
        try:
            pod_list = await self.v1.list_namespaced_pod(
                namespace=self.namespace,
                label_selector="outpost-cma/role=warm-pool"
            )
            for pod in pod_list.items:
                if pod.status.phase == "Running" and not pod.metadata.deletion_timestamp:
                    pod_name = pod.metadata.name
                    # Re-label warm pod for assigned session
                    body = {
                        "metadata": {
                            "labels": {
                                "outpost-cma/role": "sandbox",
                                "outpost-cma/session-id": session_id
                            }
                        }
                    }
                    await self.v1.patch_namespaced_pod(
                        name=pod_name,
                        namespace=self.namespace,
                        body=body
                    )
                    logger.info(f"Claimed warm pod {pod_name} for session {session_id}")
                    return pod_name
        except Exception as e:
            logger.error(f"Failed to claim warm pod: {e}")
            
        return None
