# Outpost Managed Agents: Kubernetes Execution & Orchestration Backend

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python Version](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.100+-green.svg)](https://fastapi.tiangolo.com/)

**Outpost Managed Agents** is a production-grade, open-source execution backend and standalone orchestrator for **Claude Managed Agents** designed specifically for **Kubernetes** infrastructures.

Instead of running agent code execution, bash tools, and file operations in proprietary, edge-locked environments, Outpost Managed Agents lets you deploy isolated, resource-constrained sandbox containers right inside your own Kubernetes cluster.

---

## 🚀 Key Features

*   **Dual-Mode Capability**:
    1.  **Bridge Mode (Execution Layer)**: Acts as a direct self-hosted backend replacement for Anthropic's platform. Receives webhooks, provisions isolated sandboxes, executes tools, and reports back.
    2.  **Standalone Mode (Orchestration Server)**: An API-compatible open-source clone of the Claude Managed Agents REST API (`/v1/agents`, `/v1/sessions`). Allows you to host and run agents completely privately within your network.
*   **Kubernetes-Native Sandbox Isolation**: Provisions sandboxes as lightweight pods with strict NetworkPolicies, resource constraints (CPU/Memory quotas), non-root execution, and ephemeral volume structures.
*   **Warm Pod Pooling**: Maintains a pool of pre-warmed idle sandbox pods, reducing session initialization latency from seconds to <150ms.
*   **Real-time Operations Console**: Includes a beautiful built-in admin dashboard UI to manage agents, launch sandboxes, monitor resources, and stream live execution terminals (SSE-based logging).
*   **Observability & Compliance**: Captures complete tool execution history and console stdout/stderr logs.

---

## 📐 Architecture Overview

Outpost Managed Agents splits the agent's logic ("brain") from its execution environment ("hands"):

```
                         [ CLIENT APPLICATION / SDK ]
                                      |
                      /v1/agents      |      /v1/sessions
                                      v
                       +-----------------------------+
                       |    Outpost Control Plane    |
                       |       (FastAPI Engine)      |
                       +-----------------------------+
                          /                   \
                         /                     \ (K8s API)
                        v                       v
               [(PostgreSQL/SQLite)]    [ Kubernetes Cluster ]
                 * State Database         * Sandbox Namespace
                                            ├── Pod A (Claimed)
                                            ├── Pod B (Claimed)
                                            └── Pod C (Warm Pool)
```

---

## 🛠️ Quick Start

### Prerequisites
*   Python 3.11+
*   Docker & Docker Compose
*   (Optional) A Kubernetes cluster context (`kubeconfig` or in-cluster access). If no cluster is found, Outpost Managed Agents falls back to **Local Mock Mode** for seamless local testing.

### Local Development

1. **Clone the repository and install dependencies**:
   ```bash
   git clone https://github.com/joao-aires/outpost-managed-agents.git
   cd outpost-managed-agents
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```

2. **Configure your Environment**:
   Create a `.env` file in the root:
   ```env
   ANTHROPIC_API_KEY=your-api-key-here
   DATABASE_URL=sqlite+aiosqlite:///./outpost_managed_agents.db
   KUBERNETES_NAMESPACE=agent-sandboxes
   WARM_POOL_SIZE=3
   ```

3. **Run the FastAPI Server**:
   ```bash
   uvicorn app.main:app --reload --port 8000
   ```

4. **Access the Console**:
   Open [http://localhost:8000/ui](http://localhost:8000/ui) in your browser to view the Admin Operations Console!
   *   Swagger docs are available at `/docs`.
   *   Redoc docs are available at `/redoc`.

### Running with Docker Compose
To spin up Outpost Managed Agents along with Redis:
```bash
docker-compose up --build
```

---

## 📡 REST API Reference

Outpost Managed Agents exposes Anthropic-compatible endpoints. Set the `base_url` in your Anthropic SDK initialization to point to your Outpost Managed Agents deployment.

### Agents
*   `POST /v1/agents` - Define a new agent.
*   `GET /v1/agents` - List all agent configs.
*   `GET /v1/agents/{id}` - Get agent parameters.
*   `DELETE /v1/agents/{id}` - Archive agent configuration.

### Sessions
*   `POST /v1/sessions` - Provision a new sandbox session.
*   `GET /v1/sessions` - List all active sessions.
*   `POST /v1/sessions/{id}/events` - Send message/event to the sandbox execution loop.
*   `GET /v1/sessions/{id}/events` - Establish Server-Sent Events (SSE) log & response stream.

---

## 🔒 Security Hardening (Production)

For production deployments in enterprise settings, we recommend:
1.  **Strict NetworkPolicies**: Enforce ingress/egress boundaries. Restrict sandbox pods from accessing the Kubernetes API server or internal cluster networks.
2.  **Calico or Cilium Egress Policies**: Bind sandbox pods to egress proxies to restrict traffic to whitelisted domains (e.g. `github.com`, `pypi.org`) and inject credentials dynamically.
3.  **Read-Only Filesystem**: Mount the root container filesystem as read-only, and provide writeable ephemeral directories at `/workspace` or `/tmp` using K8s `emptyDir`.

---

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
