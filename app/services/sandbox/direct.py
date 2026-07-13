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
    from kubernetes_asyncio.stream import WsApiClient
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
                await self.v1.read_namespaced_namespace(self.namespace)
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
            from kubernetes_asyncio.stream import stream
            exec_command = ["/bin/bash", "-c", command]
            
            async with WsApiClient() as ws_client:
                ws_v1 = core_v1_api.CoreV1Api(ws_client)
                resp = await stream(
                    ws_v1.connect_post_namespaced_pod_exec,
                    sandbox_id,
                    self.namespace,
                    command=exec_command,
                    stderr=True,
                    stdin=False,
                    stdout=True,
                    tty=False,
                    _preload_content=False
                )
                
                stdout_accum = []
                stderr_accum = []
                
                while resp.is_open():
                    await resp.update(timeout=1)
                    if resp.peek_stdout():
                        stdout_accum.append(resp.read_stdout())
                    if resp.peek_stderr():
                        stderr_accum.append(resp.read_stderr())
                
                return {
                    "stdout": "".join(stdout_accum),
                    "stderr": "".join(stderr_accum),
                    "exit_code": str(resp.returncode or 0)
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
        try:
            logger.info(f"Deleting sandbox pod {sandbox_id}...")
            await self.v1.delete_namespaced_pod(name=sandbox_id, namespace=self.namespace)
        except client.exceptions.ApiException as e:
            if e.status != 404:
                logger.error(f"Error deleting pod {sandbox_id}: {e}")

    async def reconcile_warm_pool(self) -> None:
        if not K8S_AVAILABLE or not self.v1:
            return

        try:
            pods = await self.v1.list_namespaced_pod(
                namespace=self.namespace,
                label_selector="outpost-cma/role=warm-pool"
            )
            current_pool_size = len([p for p in pods.items if p.status.phase == "Running"])
            needed = settings.WARM_POOL_SIZE - current_pool_size
            
            if needed <= 0:
                return

            logger.info(f"Direct pool size: {current_pool_size}/{settings.WARM_POOL_SIZE}. Spawning {needed} pods.")
            for _ in range(needed):
                warm_pod_name = f"agent-warm-{uuid.uuid4().hex[:8]}"
                pod_manifest = client.V1Pod(
                    metadata=client.V1ObjectMeta(
                        name=warm_pod_name,
                        labels={
                            "app.kubernetes.io/managed-by": "outpost-cma",
                            "outpost-cma/role": "warm-pool"
                        }
                    ),
                    spec=client.V1PodSpec(
                        containers=[
                            client.V1Container(
                                name="sandbox",
                                image=settings.SANDBOX_IMAGE,
                                command=["tail", "-f", "/dev/null"],
                                resources=client.V1ResourceRequirements(
                                    limits={"cpu": "0.5", "memory": "512Mi"},
                                    requests={"cpu": "0.1", "memory": "128Mi"}
                                )
                            )
                        ],
                        restart_policy="Never"
                    )
                )
                await self.v1.create_namespaced_pod(namespace=self.namespace, body=pod_manifest)
        except Exception as e:
            logger.error(f"Failed pool reconciliation: {e}")

    async def _claim_warm_pod(self, session_id: str) -> Optional[str]:
        try:
            pods = await self.v1.list_namespaced_pod(
                namespace=self.namespace,
                label_selector="outpost-cma/role=warm-pool"
            )
            running_pods = [p for p in pods.items if p.status.phase == "Running"]
            if not running_pods:
                return None
                
            target_pod = running_pods[0]
            pod_name = target_pod.metadata.name
            
            patch = {
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
                body=patch
            )
            return pod_name
        except Exception as e:
            logger.error(f"Failed to claim warm pod: {e}")
            return None
