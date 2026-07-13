# Feature Analysis & Implementation Plan: Outpost Managed Agents

This document analyzes the complete feature set of **Claude Managed Agents** based on Anthropic platform specifications and outlines the implementation plan to bring 100% parity to **Outpost Managed Agents**.

---

## 1. Feature Mapping & Gap Analysis

| Claude Managed Agent Feature | Anthropic Specification | Outpost Implementation Strategy |
| :--- | :--- | :--- |
| **Agent Configuration** | Profiles, System Prompt, Custom Models | Fully implemented in [agent.py](file:///Users/airesjoa/MEGA/personal/outpost-managed-agents/app/models/agent.py) |
| **Sandboxed Tool Execution** | Safe execution of bash, file ops, etc. | Implemented via `BaseSandboxDriver` + K8s exec |
| **Stateful Sessions** | Stateful event queue, SSE status stream | Implemented via [orchestrator.py](file:///Users/airesjoa/MEGA/personal/outpost-managed-agents/app/services/orchestrator.py) |
| **File Management** | Uploading files, mounting inside sessions | **Gap**: Needs dedicated Files API & S3/PVC mounts |
| **Session Memory** | Long-term memory stores across sessions | **Gap**: Needs Persistent Volumes (PVC) in K8s |
| **Multi-Agent Orchestration** | Session spawning child sessions/subagents | **Gap**: Needs orchestrator-side `invoke_subagent` tool |
| **MCP Integration** | Model Context Protocol servers mapping | **Gap**: Needs sidecar containers in Sandbox Pods |
| **Web Tools** | Headless browsing & web searching | **Gap**: Needs Playwright/Search API integrations |

---

## 2. Phase-by-Phase Implementation Plan

### Phase 1: Files API & Persistent Session Workspace (`/v1/files`)
*   **Goal**: Allow users to upload datasets, scripts, or images, making them accessible inside the sandbox container.
*   **API Design**:
    *   `POST /v1/files`: Uploads a file (multipart upload).
    *   `GET /v1/files`: List files.
    *   `DELETE /v1/files/{file_id}`: Remove file.
*   **Kubernetes Storage**:
    *   Uploaded files are stored in a Shared Storage volume (e.g., AWS EFS, MinIO, or a local path).
    *   When a Session starts, Outpost provisions a **Kubernetes Persistent Volume Claim (PVC)** for the session and mounts it at `/workspace`.
    *   Uploaded files are copied into the workspace before the container starts, ensuring persistent, durable files across container crashes.

### Phase 2: Multi-Agent Orchestration (Delegation Engine)
*   **Goal**: Allow a coordinator agent to spawn sub-agents to process tasks concurrently in separate sandboxes.
*   **Implementation**:
    1.  Inject a built-in `delegate_task` tool to the agent:
        ```json
        {
          "name": "delegate_task",
          "description": "Spawn a specialized sub-agent to execute a sub-task.",
          "input_schema": {
            "type": "object",
            "properties": {
              "agent_id": { "type": "string", "description": "Target agent profile ID." },
              "prompt": { "type": "string", "description": "The specific task instructions." }
            },
            "required": ["agent_id", "prompt"]
          }
        }
        ```
    2.  When the agent invokes `delegate_task`, the `AgentOrchestrator`:
        *   Spawns a new child `Session` in the database.
        *   Triggers a run queue for the child.
        *   Establishes an internal SSE subscriber to monitor the child's events.
        *   Blocks the parent's loop execution until the child session reaches `completed` or returns a final result.
        *   Feeds the child's final outcome back to the parent agent.

### Phase 3: Model Context Protocol (MCP) Server Sidecars
*   **Goal**: Allow agents to hook into standard MCP servers (e.g., PostgreSQL client, GitHub tools) running securely.
*   **Kubernetes Pod Architecture**:
    *   Instead of running the MCP server inside the main sandbox container, we run the MCP server as a **Sidecar container** inside the same Kubernetes Pod.
    *   The main Sandbox container communicates with the MCP sidecar over localhost (e.g., `http://localhost:8080/mcp`) using secure local port mappings.
    *   Secrets and configurations are injected directly into the sidecar, completely hidden from the agent.

```
┌──────────────────────────────────────────────┐
│             Kubernetes Sandbox Pod           │
│                                              │
│  ┌──────────────────┐      (localhost)       │
│  │  Main Container  │◄───────────────────┐   │
│  │ (Bash / Python)  │                    │   │
│  └──────────────────┘                    ▼   │
│                            ┌─────────────────┐
│                            │   MCP Sidecar   │
│                            │ (GitHub/DB Tool)│
│                            └─────────────────┘
└──────────────────────────────────────────────┘
```

### Phase 4: Headless Browsing & Search Integration
*   **Goal**: Support native web browsing (Playwright/Puppeteer) and web search tools.
*   **Implementation**:
    *   Update [Dockerfile.sandbox](file:///Users/airesjoa/MEGA/personal/outpost-managed-agents/Dockerfile.sandbox) to include Playwright and Chromium.
    *   Expose a browser agent script tool (`browse_url`) that runs Chromium in headless mode, capturing screenshots, and extracting markdown/text.
    *   In the Admin UI, support a **Live VNC View** to allow developers to watch the agent interact with websites inside the pod.
