# Aligned Architecture: Sandbox Agent Interface (SAI)

Following our design review, this document maps the aligned, finalized architecture for the **Sandbox Agent Interface (SAI)** in Outpost Managed Agents.

---

## 1. Core Architecture Decisions

### 1.1 Manifest Discovery & Storage
*   **Mechanism**: **Hybrid**.
*   **Behavior**: Default manifests (e.g. `claude-code`, `opencode`) are pre-loaded from a local directory (e.g. `app/runtimes/`) at startup. Custom, user-defined manifests submitted via `POST /v1/coding-agents` are stored in the database.
*   **Parity**: Outpost merges defaults and custom definitions at runtime.

### 1.2 Interactive PTY / Terminal Streaming
*   **Mechanism**: **FastAPI WebSockets Gateway**.
*   **Behavior**: Outpost exposes a WebSocket endpoint `/v1/sessions/{id}/terminal`.
    *   The frontend browser connects to this WebSocket.
    *   The FastAPI backend establishes a corresponding WebSocket channel to the Kubernetes API exec endpoint (`connect_post_namespaced_pod_exec`) with `tty=True`.
    *   FastAPI proxies keystroke inputs from the browser directly to the pod shell's stdin, and parses K8s output frames (removing transport envelopes) before streaming stdout/stderr back to the browser.
    *   **Auditing**: Every command forwarded to the PTY stdin is logged and timestamped in PostgreSQL for operational auditing.

### 1.3 Secret Vault Injection
*   **Mechanism**: **Dynamic Kubernetes Secrets**.
*   **Behavior**:
    *   When a session starts, Outpost reads the manifest's `variables` schema and maps user-supplied secret credentials (e.g. `ANTHROPIC_API_KEY`).
    *   Outpost creates a temporary Kubernetes `Secret` object named `secret-session-{id}`:
        ```yaml
        apiVersion: v1
        kind: Secret
        metadata:
          name: secret-session-123
        stringData:
          ANTHROPIC_API_KEY: "sk-ant-..."
        ```
    *   The secret keys are mounted into the Pod specification as environment variables using `envFrom` or `valueFrom.secretKeyRef`.
    *   **Cleanup**: When the session ends, the temporary Secret resource is deleted along with the Pod.

### 1.4 Cache State Persistence
*   **Mechanism**: **Dynamic Persistent Volume Claims (PVC)**.
*   **Behavior**:
    *   For each running session, Outpost creates a small persistent volume claim (`outpost-pvc-session-{id}`) using the cluster's default storage class (e.g., `gp3` or local path).
    *   The volume is mounted into the Pod at the directories specified by the manifest's `persistent_paths` (e.g. `/home/agent/.claude` or `/home/agent/.cursor`).
    *   This guarantees that if the pod crashes, is rescheduled, or updated, the user's terminal authorization token and local command-line caches are preserved.

### 1.5 Terminal Console Emulator
*   **Mechanism**: **Xterm.js Canvas Engine**.
*   **Behavior**: The Operations UI integrates the `xterm.js` package. It captures raw ANSI stream chunks from the WebSocket gateway, supporting standard shell colors, responsive window dimensions, text selections, and keyboard navigation.

---

## 2. Updated Manifest Specification Schema

Here is the exact schema implemented for `AgentRuntimeManifest`:

```json
{
  "id": "claude-code",
  "name": "Claude Code",
  "sandbox": {
    "default_image": "node:20-slim",
    "persistent_paths": [
      {
        "name": "claude-cache",
        "mount_path": "/home/agent/.claude"
      }
    ]
  },
  "variables": [
    {
      "name": "ANTHROPIC_API_KEY",
      "required": true,
      "secret": true,
      "description": "API Key for model billing"
    }
  ],
  "lifecycle": {
    "setup": "npm install -g @anthropic-ai/claude-code && claude --version",
    "pre_run": "echo 'Verifying credentials...'",
    "run_interactive": "claude",
    "run_task": "claude --print {prompt}",
    "teardown": "echo 'Cleaning up...'"
  }
}
```

---

## 3. Database Schema

The following tables are added to support the aligned configurations:

```sql
CREATE TABLE coding_agents (
    id VARCHAR(100) PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    description TEXT,
    manifest JSONB NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE session_audit_logs (
    id SERIAL PRIMARY KEY,
    session_id VARCHAR(36) NOT NULL REFERENCES sessions(id),
    command TEXT NOT NULL,
    executed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```
