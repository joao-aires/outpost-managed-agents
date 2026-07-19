# Production-Grade System Specification: Outpost Managed Agents

This document defines the architectural specifications and system design required to bring **Outpost Managed Agents** to production-grade security, scalability, and observability.

---

## 1. Multi-Tenant Authentication & Identity Isolation

To support multiple users and enterprise teams safely, Outpost implements a **Multi-Tenant JWT (OAuth2 / OpenID Connect)** architecture:

```
 [ Client / Browser ] ──(1. Login)──> [ Identity Provider (Keycloak / Auth0) ]
          │                                     │
          ├──(2. REST + Bearer Token)───────────┤ (Generates JWT)
          ▼
 ┌────────────────────────────────────────────────────────────────────────┐
 │                      Outpost Gateway / API                             │
 └──────────────────┬───────────────────────────────┬─────────────────────┘
                    │                               │
                    ▼ (Teant DB isolation)          ▼ (K8s Namespace Isolation)
              [(PostgreSQL Schema)]        [ K8s Namespace: tenant-{id} ]
```

### 1.1 Architecture Details
*   **Authentication**: FastAPI validates incoming JWTs against the configured OIDC discovery endpoint (JWKS).
*   **Tenant Mapping**: The `tenant_id` claim is extracted from the token.
    *   **Database Isolation**: Outpost uses PostgreSQL row-level security (RLS) or separates tables dynamically by schema to ensure tenants cannot read or write each other's agent or session metadata.
    *   **Compute Isolation**: Each session is provisioned in a dedicated Kubernetes namespace named `outpost-tenant-{tenant_id}`. This prevents cross-tenant network traffic or pod inspection.

---

## 2. Hardened Sandbox Isolation (Layered Security)

To safeguard the Kubernetes host node from arbitrary, LLM-generated code, Outpost implements a **Defense-in-Depth Security Model** combining three layers:

```
  ┌───────────────────────────────────────────────────────────────┐
  │                   Layer 3: Dedicated Node Pool                │
  │  (Taints: agent-only=true, Tolerations: agent-only=true)      │
  │  ┌─────────────────────────────────────────────────────────┐  │
  │  │               Layer 2: gVisor / Kata Container          │  │
  │  │  (RuntimeClass: gvisor or kata)                         │  │
  │  │  ┌───────────────────────────────────────────────────┐  │  │
  │  │  │           Layer 1: SecurityContext & NetPol       │  │  │
  │  │  │  (runAsNonRoot: true, NetworkPolicy default-deny) │  │  │
  │  │  └───────────────────────────────────────────────────┘  │  │
  │  └─────────────────────────────────────────────────────────┘  │
  └───────────────────────────────────────────────────────────────┘
```

### 2.1 Layer 1: Container Hardening & NetworkPolicies
*   **Default-Deny NetworkPolicy**: Pods cannot talk to the cluster's internal network, the CoreDNS endpoint (except on port 53), or the Kubernetes API Server.
*   **SecurityContext**:
    *   `runAsNonRoot: true` and `runAsUser: 1000` (User: `agent`).
    *   `readOnlyRootFilesystem: true` (only `/workspace` is writeable via an ephemeral `emptyDir`).
    *   `allowPrivilegeEscalation: false` and dropping all Linux capabilities (`capabilities: { drop: ["ALL"] }`).

### 2.2 Layer 2: Secure Runtime Classes
*   Pods are injected with a designated `runtimeClassName` (e.g., `gvisor` or `kata-containers`).
*   **gVisor** intercepts all container syscalls and runs them in a user-space kernel wrapper (`runsc`), preventing container escapes.
*   **Fallback**: If the target cluster does not have `gvisor` configured, Outpost falls back dynamically to standard runtimes but keeps Layer 1 rules enforced.

### 2.3 Layer 3: Tainted Node Pools
*   Workloads are scheduled on dedicated worker node groups labeled and tainted:
    *   Taint: `outpost-sandbox=true:NoSchedule`
    *   Sandbox Pods are injected with tolerations for this taint, ensuring that if a breakout *does* occur, only disposable agent-only nodes are compromised, keeping control plane and DB nodes secure.

---

## 3. Egress Control & Secret Masking Sidecar

To prevent agents from leaking API credentials or connecting to command-and-control (C2) domains, Outpost uses an **Egress Proxy Sidecar**:

```
 ┌────────────────────────────────────────────────────────────────────────┐
 │                         Agent Sandbox Pod                              │
 │                                                                        │
 │  ┌──────────────────┐               ┌───────────────────────────────┐  │
 │  │ Agent Container  │──(egress request)─►│     Egress Proxy Sidecar     │  │
 │  │                  │               │ (Envoy / Custom Go proxy)     │  │
 │  └──────────────────┘               └──────────────┬────────────────┘  │
 └────────────────────────────────────────────────────┼───────────────────┘
                                                      │
                                                      │ (Injects credentials &
                                                      │  filters domains)
                                                      ▼
                                              [ Safe API Endpoint ]
```

### 3.1 Egress Proxy Behavior
1.  **Traffic Interception**: All outgoing HTTP/HTTPS traffic from the agent container is hijacked via `iptables` rules and routed to the proxy sidecar.
2.  **Domain Filtering**: The proxy checks request hostnames against the manifest's allowed domain whitelist. Unlisted domains are dropped immediately.
3.  **Header Injection**: Instead of giving raw keys (e.g., `ANTHROPIC_API_KEY`) to the agent, the agent sends requests with a placeholder header (e.g., `X-Outpost-Auth: anthropic`). The proxy intercepts the request, replaces it with the actual credential from the vault, and forwards it.
4.  **Leak Prevention**: Raw keys are never loaded into the agent's environment or filesystem.

---

## 4. Distributed Task Queue (ARQ / Redis)

To handle scale, rate-limiting, and recover from backend crashes, the execution loop is offloaded from the web server using **ARQ (Redis-backed worker loops)**:

```
  [ Client Request ] ──► [ FastAPI API Server ]
                                │
                                ├─ (Enqueues Job)
                                ▼
                       ┌─────────────────┐
                       │   Redis Queue   │
                       └────────┬────────┘
                                │
                                ▼ (Pulls Job)
                       ┌─────────────────┐
                       │   ARQ Worker    │◄───► [ K8s Pod Exec ]
                       └─────────────────┘
```

### 4.1 Scalability Specs
*   **Horizontal Scaling**: FastAPI web servers and ARQ workers scale independently. Workers can run on separate nodes closer to the Kubernetes cluster.
*   **Rate-Limiting**: ARQ implements token bucket rate-limiting per user/tenant to prevent overloading downstream LLM endpoints (like Anthropic API rate limits).
*   **Job Recovery**: If a worker node dies mid-execution, Redis retains the job state, and another worker picks up and reconciles the sandbox loop.

---

## 5. Observability: Raw Text Logs via OpenTelemetry

For log aggregation and compliance, Outpost bypasses terminal replay formats in favor of **Structured OpenTelemetry Streams**:

### 5.1 Architecture Details
*   **Log Forwarding**: A Fluentbit or Promtail sidecar sits inside the sandbox Pod, reading stdout/stderr streams from the agent workspace.
*   **Standardized Spans**: All agent tool runs and bash commands are packaged as OpenTelemetry Span events.
*   **Target Backends**: Logs are pushed directly to centralized systems (like **Grafana Loki** or **Elasticsearch**).
*   **UI Integration**: The Admin Console queries Loki APIs to show near-real-time terminal dumps and debug streams.
