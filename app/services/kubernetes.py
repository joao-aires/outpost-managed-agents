import asyncio
import logging
import base64
import uuid
from typing import Dict, List, Optional
from app.config import settings

logger = logging.getLogger("outpost_cma.kubernetes")

# Attempt to load kubernetes asyncio SDK
try:
    from kubernetes_asyncio import client, config
    from kubernetes_asyncio.client.api import core_v1_api
    from kubernetes_asyncio.stream import WsApiClient
    K8S_AVAILABLE = True
except ImportError:
    K8S_AVAILABLE = False
    logger.warning("kubernetes-asyncio library not installed. Falling back to Mock/Local execution mode.")

class KubeSandboxClient:
    """
    Manages Kubernetes Pod sandboxes for Agent execution.
    Features: pod creation, command execution, file management, and warm pod pooling.
    """
    def __init__(self):
        self.namespace = settings.KUBERNETES_NAMESPACE
        self.initialized = False
        self.v1 = None
        self.api_client = None

    async def initialize(self):
        if not K8S_AVAILABLE:
            logger.info("Kubernetes client not available. Operating in Local Mock Mode.")
            self.initialized = True
            return
            
        try:
            # Try to load in-cluster config first, then fall back to kube_config
            try:
                config.load_incluster_config()
                logger.info("Loaded in-cluster Kubernetes configuration.")
            except Exception:
                await config.load_kube_config()
                logger.info("Loaded local kubeconfig.")
            
            self.api_client = client.ApiClient()
            self.v1 = core_v1_api.CoreV1Api(self.api_client)
            self.initialized = True
            
            # Ensure the namespace exists
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
            logger.error(f"Failed to initialize Kubernetes client: {e}. Falling back to Local Mock Mode.")
            K8S_AVAILABLE = False
            self.initialized = True

    async def create_sandbox_pod(self, session_id: str) -> str:
        """
        Creates a new sandboxed Pod or claims one from the warm pool.
        """
        if not self.initialized:
            await self.initialize()

        pod_name = f"agent-sandbox-{session_id[:8]}-{uuid.uuid4().hex[:6]}"

        if not K8S_AVAILABLE:
            logger.info(f"[MOCK] Created virtual sandbox container for session {session_id}: {pod_name}")
            return pod_name

        # Try to claim a warm pod first
        claimed_pod = await self._claim_warm_pod(session_id)
        if claimed_pod:
            logger.info(f"Claimed warm pod {claimed_pod} for session {session_id}")
            return claimed_pod

        # Build Pod Manifest
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
                            run_as_group=1000,
                            read_only_root_filesystem=False # Set to True in production with ephemeral volume mounts
                        )
                    )
                ],
                restart_policy="Never",
                termination_grace_period_seconds=5
            )
        )

        logger.info(f"Creating pod {pod_name} in namespace {self.namespace}...")
        await self.v1.create_namespaced_pod(namespace=self.namespace, body=pod_manifest)

        # Wait for the Pod to be ready (running)
        for _ in range(30):
            pod = await self.v1.read_namespaced_pod(name=pod_name, namespace=self.namespace)
            if pod.status.phase == "Running":
                logger.info(f"Pod {pod_name} is running.")
                return pod_name
            await asyncio.sleep(1)

        raise TimeoutError(f"Pod {pod_name} failed to reach Running state in time.")

    async def execute_command(self, pod_name: str, command: str) -> Dict[str, str]:
        """
        Executes a bash command inside the sandbox container.
        Returns a dict with: 'stdout', 'stderr', and 'exit_code'.
        """
        if not K8S_AVAILABLE:
            logger.info(f"[MOCK CMD] Running on {pod_name}: {command}")
            # Mocking command execution
            if command.strip() == "pwd":
                return {"stdout": "/workspace\n", "stderr": "", "exit_code": "0"}
            if command.strip() == "whoami":
                return {"stdout": "agent\n", "stderr": "", "exit_code": "0"}
            return {"stdout": f"Mock output for: {command}\n", "stderr": "", "exit_code": "0"}

        try:
            from kubernetes_asyncio.stream import stream
            exec_command = ["/bin/bash", "-c", command]
            
            # Use WsApiClient for streaming exec over WebSockets
            async with WsApiClient() as ws_client:
                # Need to use standard CoreV1Api with WebSocket client
                ws_v1 = core_v1_api.CoreV1Api(ws_client)
                resp = await stream(
                    ws_v1.connect_post_namespaced_pod_exec,
                    pod_name,
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
                
                # Check execution return code
                exit_code = resp.returncode
                
                return {
                    "stdout": "".join(stdout_accum),
                    "stderr": "".join(stderr_accum),
                    "exit_code": str(exit_code or 0)
                }
        except Exception as e:
            logger.error(f"Failed to execute command on pod {pod_name}: {e}")
            return {"stdout": "", "stderr": str(e), "exit_code": "1"}

    async def read_file(self, pod_name: str, path: str) -> bytes:
        """
        Reads a file from the sandbox by base64 encoding it via exec.
        """
        result = await self.execute_command(pod_name, f"cat {path} | base64")
        if result["exit_code"] != "0":
            raise FileNotFoundError(f"Failed to read file {path}: {result['stderr']}")
        return base64.b64decode(result["stdout"].strip())

    async def write_file(self, pod_name: str, path: str, content: bytes) -> bool:
        """
        Writes a file to the sandbox by base64 decoding content inside the container.
        """
        b64_content = base64.b64encode(content).decode("utf-8")
        # Ensure target directory exists
        dir_path = "/".join(path.split("/")[:-1])
        if dir_path:
            await self.execute_command(pod_name, f"mkdir -p {dir_path}")
            
        cmd = f"echo '{b64_content}' | base64 -d > {path}"
        result = await self.execute_command(pod_name, cmd)
        return result["exit_code"] == "0"

    async def delete_sandbox_pod(self, pod_name: str):
        """
        Deletes the sandbox pod.
        """
        if not K8S_AVAILABLE:
            logger.info(f"[MOCK] Deleted sandbox pod {pod_name}")
            return

        try:
            logger.info(f"Deleting pod {pod_name} in namespace {self.namespace}...")
            await self.v1.delete_namespaced_pod(name=pod_name, namespace=self.namespace)
        except client.exceptions.ApiException as e:
            if e.status != 404:
                logger.error(f"Error deleting pod {pod_name}: {e}")

    # --- Warm Pod Pool management ---
    
    async def _claim_warm_pod(self, session_id: str) -> Optional[str]:
        """
        Finds an idle pod from the warm pool and claims it by updating labels.
        """
        try:
            # List pods in pool
            pods = await self.v1.list_namespaced_pod(
                namespace=self.namespace,
                label_selector="outpost-cma/role=warm-pool"
            )
            if not pods.items:
                return None
                
            # Pick first available pod
            target_pod = pods.items[0]
            pod_name = target_pod.metadata.name
            
            # Patch labels to assign to session
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

    async def reconcile_warm_pool(self):
        """
        Ensures the warm pool size matches configuration.
        """
        if not K8S_AVAILABLE or not self.initialized:
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

            logger.info(f"Warm pool size: {current_pool_size}/{settings.WARM_POOL_SIZE}. Spawning {needed} warm pods.")
            for _ in range(needed):
                # Spawn a warm pod
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
                                ),
                                security_context=client.V1SecurityContext(
                                    allow_privilege_escalation=False,
                                    run_as_user=1000,
                                    run_as_group=1000,
                                    read_only_root_filesystem=False
                                )
                            )
                        ],
                        restart_policy="Never"
                    )
                )
                await self.v1.create_namespaced_pod(namespace=self.namespace, body=pod_manifest)
                logger.info(f"Spawned warm pool pod: {warm_pod_name}")
        except Exception as e:
            logger.error(f"Error during warm pool reconciliation: {e}")

# Singleton Instance
sandbox_client = KubeSandboxClient()
