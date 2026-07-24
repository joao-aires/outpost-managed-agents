# Outpost Architecture Specification: Control Plane & Data Plane Decoupling

* **Status**: Proposed / Architectural Specification
* **Date**: 2026-07-24
* **Target Audience**: Outpost Core Engineering Team

---

## 🌐 1. Overview & Architectural Motivation

To support **Bring Your Own Cloud (BYOC)**, multi-cluster enterprise deployments, and high-margin SaaS monetization, Outpost Managed Agents must decouple its monolithic architecture into two distinct operating planes:

1. **Centralized Control Plane**: Hosted by Outpost (or self-hosted by enterprise IT). Manages `/v1/agents`, `/v1/sessions` REST APIs, LLM reasoning loops, turn state, dashboard UI, and billing metering.
2. **Distributed Data Plane (Outpost K8s Runner Daemon)**: Deployed inside customer-owned Kubernetes clusters (EKS, GKE, AKS, OpenShift, On-Prem). Manages warm pod pools, container lifecycles, volume mounts, eBPF security policies, and local tool executions.

```
┌─────────────────────────────────────────────────────────────────────────────────────────┐
│                          CENTRALIZED CONTROL PLANE (Hosted / SaaS)                      │
│                                                                                         │
│  • FastAPI REST & SSE Gateway (/v1/agents, /v1/sessions)                                │
│  • Agent Registry & Database (PostgreSQL / SQLite)                                      │
│  • LLM Turn Orchestrator & Reasoning Loop (BYOB)                                        │
│  • gRPC Control Tunnel Server (mTLS / SPIFFE Token Exchange)                            │
└─────────────────────────────────────────────────────────────────────────────────────────┘
                                             │
                                             │ Bi-Directional gRPC Tunnel (Outbound from K8s)
                                             ▼
┌─────────────────────────────────────────────────────────────────────────────────────────┐
│                     DISTRIBUTED DATA PLANE (Customer Kubernetes Cluster)                │
│                                                                                         │
│  ┌────────────────────────────────────────────────────────────────────────────────────┐ │
│  │ 📦 Outpost Data Plane Runner Daemon (outpost-runner)                               │ │
│  │    • Maintains mTLS gRPC connection to Control Plane                               │ │
│  │    • Runs DirectPodDriver locally in customer namespace (`agent-sandboxes`)       │ │
│  │    • Manages Warm Pod Pool & HostPath Cache DaemonSet                               │ │
│  └────────────────────────────────────────────────────────────────────────────────────┘ │
│                                             │                                           │
│                                             ▼                                           │
│  ┌────────────────────────────────────────────────────────────────────────────────────┐ │
│  │ 🔒 Isolated Sandbox Pods (gVisor, ReadOnlyRootFS, NetworkPolicy)                   │ │
│  │    • Customer source code, internal databases, & proprietary data STAY HERE.      │ │
│  └────────────────────────────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────────────────────────┘
```

---

## 🛠️ 5 Core Architectural Changes Required

### 1. Abstract `BaseSandboxDriver` for Remote Data Planes (`app/services/sandbox/`)

**Current State**: `DirectPodDriver` in `app/services/sandbox/direct.py` invokes local `kubernetes_asyncio` and `kubectl` directly inside the monolith.

**Required Change**:
* Implement `RemoteDataPlaneDriver(BaseSandboxDriver)` in `app/services/sandbox/remote.py`.
* `RemoteDataPlaneDriver` proxies sandbox RPC calls (`create_sandbox`, `execute_command`, `read_file`, `write_file`, `delete_sandbox`) over an active gRPC stream to the customer's remote cluster runner.

```python
class RemoteDataPlaneDriver(BaseSandboxDriver):
    def __init__(self, cluster_id: str):
        self.cluster_id = cluster_id
        self.grpc_client = DataPlaneTunnelManager.get_client(cluster_id)

    async def create_sandbox(self, session_id: str) -> str:
        response = await self.grpc_client.ProvisionSandbox(
            ProvisionRequest(session_id=session_id)
        )
        return response.sandbox_id
```

---

### 2. Define the gRPC Protocol Buffer Specification (`proto/dataplane.proto`)

Establish a formal gRPC protocol buffer contract between Control Plane and Data Plane Runners:

```protobuf
syntax = "proto3";

package outpost.dataplane.v1;

service DataPlaneRunner {
  // Sandbox Lifecycle RPCs
  rpc ProvisionSandbox (ProvisionRequest) returns (ProvisionResponse);
  rpc TerminateSandbox (TerminateRequest) returns (TerminateResponse);
  
  // Execution RPCs
  rpc ExecuteCommand (ExecuteCommandRequest) returns (ExecuteCommandResponse);
  rpc ReadFile (ReadFileRequest) returns (ReadFileResponse);
  rpc WriteFile (WriteFileRequest) returns (WriteFileResponse);

  // Bi-directional Stream for Telemetry & Real-Time Tool Approvals (ADR 0003)
  rpc StreamTelemetry (stream TelemetryEvent) returns (stream ControlCommand);
}

message ProvisionRequest {
  string session_id = 1;
  string harness_type = 2; // claude-code, opencode, etc.
  string image = 3;
  bool read_only_root_fs = 4;
}

message ProvisionResponse {
  string sandbox_id = 1;
  string pod_ip = 2;
  int32 status_code = 3;
}
```

---

### 3. Outpost Cluster & Tenant Registration Model (`app/models/cluster.py`)

Add a cluster registration domain model to track customer Kubernetes runners:

```python
from pydantic import BaseModel
from datetime import datetime
from typing import Optional

class ClusterRegistration(BaseModel):
    cluster_id: str
    tenant_id: str
    cluster_name: str
    status: str  # ONLINE, OFFLINE, DEGRADED
    spiffe_id: str
    active_sandboxes: int
    last_heartbeat: datetime
    region: Optional[str] = "us-east-1"
```

* **Cluster Heartbeat Monitor**: Control Plane monitors gRPC keepalives every 10s. If a cluster disconnects, its status switches to `OFFLINE` and new session creations on that cluster are blocked.

---

### 4. Outbound gRPC Tunneling (No Inbound Firewall Rules Needed)

**Security Requirement**: Enterprise IT will not open inbound ports on their private Kubernetes firewalls.

**Solution**:
* The **Outpost Data Plane Runner Daemon** initiates an **outbound gRPC connection over mTLS** (port 443) from the customer cluster to the Outpost Control Plane.
* Uses bi-directional HTTP/2 gRPC streaming (gRPC Tunneling). The Control Plane sends sandbox provisioning requests back down the existing outbound connection.

---

### 5. Two-Tier Identity & Short-Lived Token Exchange (`app/services/iam.py`)

Integrate **RFC 8693 OAuth 2.0 Token Exchange**:
1. Control Plane generates a short-lived (5-minute) **Workload Transaction Token** scoped strictly to `session_id` and `cluster_id`.
2. When the Data Plane Runner executes tools, it validates the token signature locally before executing commands inside the sandbox pod.
3. Static secrets (GitHub PATs, AWS keys) never leave the Control Plane Vault; they are injected in-flight by the Data Plane Egress Proxy (ADR 0004).

---

## 📅 Phased Implementation Roadmap

| Phase | Core Objective | Key Deliverables |
| :--- | :--- | :--- |
| **Phase 1** | Interface Abstraction | Create `proto/dataplane.proto` & abstract `RemoteDataPlaneDriver`. |
| **Phase 2** | gRPC Tunnel Server | Build `DataPlaneTunnelManager` in Control Plane with mTLS authentication. |
| **Phase 3** | Data Plane Runner Daemon | Package `outpost-runner` Helm chart for customer Kubernetes clusters. |
| **Phase 4** | Cluster Management UI | Add Cluster Registration & Heartbeat Dashboard to Outpost Console. |
