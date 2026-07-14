# Blueprint: Declarative Sandbox Agent Interface (SAI)

This blueprint defines the architecture and finalized design decisions for the **Sandbox Agent Interface (SAI)** in Outpost Managed Agents.

Outpost contains **no** hardcoded logic or models for specific coding agents. Instead, the interface between Outpost and any coding agent is defined by a **Declarative Runtime Manifest** (`AgentRuntimeManifest`). Outpost behaves as a generic container scheduler, secret vault, and interactive terminal relay (PTY) that executes the lifecycle hooks defined in the agent's manifest.

---

## 1. Finalized Architectural Decisions (Aligned)

Through interactive architectural review, the following decisions have been finalized:

### 1.1 Manifest Discovery & Storage
*   **Decision**: **Hybrid**.
*   **Behavior**: Built-in default agent manifests (e.g., `claude-code`, `opencode`) are pre-loaded from a local directory (`app/runtimes/`) at startup. Custom manifests uploaded by users via the Admin UI/REST APIs are saved in the database (`coding_agents` table). Outpost merges both sources dynamically.

### 1.2 Interactive PTY / Terminal Streaming
*   **Decision**: **FastAPI WebSockets Gateway**.
*   **Behavior**: Outpost exposes a WebSocket endpoint `/v1/sessions/{id}/terminal`. 
    *   FastAPI acts as a proxy, translating browser WebSockets into K8s exec streams frame-by-frame (`tty=True`).
    *   Centralized Command Auditing: Outpost intercepts and logs all command inputs forwarded to the PTY stdin, saving them into the `session_audit_logs` table for logging and security compliance.
    *   **Frontend**: Rendered using the `xterm.js` canvas engine in the operations console to support colors, interactive menus, and layout resizing.

### 1.3 Secret Vault Injection
*   **Decision**: **Dynamic Kubernetes Secrets**.
*   **Behavior**: At session startup, Outpost reads the manifest's `variables` schema and creates a temporary Kubernetes `Secret` resource (`secret-session-{id}`). These keys are safely mounted into the Pod using K8s `envFrom` or `valueFrom.secretKeyRef` constraints. Secrets are deleted from the cluster once the session is terminated.

### 1.4 Cache State Persistence
*   **Decision**: **Dynamic Persistent Volume Claims (PVC)**.
*   **Behavior**: Outpost creates a small Persistent Volume Claim (`outpost-pvc-session-{id}`) using the cluster's default storage class, mounted to the container paths declared in the manifest's `persistent_paths` (e.g., `~/.claude` or `~/.cursor`). This prevents developers from losing authorization and session logins.

---

## 2. The Declarative Manifest Interface (`agent-runtime.yaml`)

Every coding agent is defined by a YAML manifest following this exact interface schema:

```yaml
# Example: app/runtimes/claude-code.yaml
id: "claude-code"
name: "Claude Code"
version: "0.1.0"

# 1. Container Sandbox Requirements
sandbox:
  default_image: "node:20-slim"
  read_only_rootfs: false
  resources:
    limits:
      cpu: "1"
      memory: "1Gi"
    requests:
      cpu: "0.2"
      memory: "256Mi"
  # Paths that must persist across container restarts (mounted via K8s PVC)
  persistent_paths:
    - name: "claude-cache"
      mount_path: "/home/agent/.claude"

# 2. Variable & Secret Definitions (Injected by Outpost at startup via K8s Secrets)
variables:
  - name: "ANTHROPIC_API_KEY"
    required: true
    secret: true
    description: "API Key for model requests and billing"
  - name: "SHELL"
    required: false
    default: "/bin/bash"

# 3. Lifecycle Execution Interface (Shell commands Outpost runs inside the Pod)
lifecycle:
  # Setup: Run once to install or verify the coding agent CLI in the container
  setup: |
    if ! command -v claude &> /dev/null; then
      echo "Installing Claude Code CLI..."
      npm install -g @anthropic-ai/claude-code
    fi
    claude --version

  # Pre-run: Verify authentication or check configs before starting
  pre_run: |
    if [ -z "$ANTHROPIC_API_KEY" ]; then
      echo "Error: ANTHROPIC_API_KEY is not set."
      exit 1
    fi

  # Interactive Run: Command executed inside a Pseudo-Terminal (PTY) session
  run_interactive: "claude"

  # Task Run: Command executed for non-interactive single prompts
  run_task: "claude --print {prompt}"

  # Cleanup: Optional hook run on termination
  teardown: "echo 'Cleaning up session...'"
```

---

## 3. Outpost Control Plane Execution Flow

The Outpost backend implements a generic **Lifecycle Executor Engine**:

```
                  [ USER START SESSION REQUEST ]
                                │ (Passes AgentRuntimeManifest)
                                ▼
 ┌─────────────────────────────────────────────────────────────┐
 │                    Outpost Control Plane                    │
 └──────────────────────────────┬──────────────────────────────┘
                                │
                                ├─ 1. Reads 'sandbox' requirements
                                ├─ 2. Creates dynamic K8s Secrets & PVCs
                                ├─ 3. Provisions generic K8s Pod
                                ▼
 ┌─────────────────────────────────────────────────────────────┐
 │                Kubernetes Pod Sandbox                       │
 └──────────────────────────────┬──────────────────────────────┘
                                │
                                ├─ 4. Runs 'lifecycle.setup' via exec API
                                ├─ 5. Runs 'lifecycle.pre_run'
                                ├─ 6. Opens a WebSocket PTY to 'run_interactive'
                                ▼
                [ INTERACTIVE TERMINAL RELAY ]
                 User Keyboard <───> Agent Stdin/Stdout
```

### 3.1 Bootstrapping Phase (`setup`)
When a session is initiated, Outpost provisions a container running the specified `default_image`. It then issues the `lifecycle.setup` commands inside the container using the Kubernetes exec API to pull and configure the coding agent.

### 3.2 Interactive PTY Relay (`run_interactive`)
To support terminal-based coding agents like Claude Code, the Outpost backend executes the `run_interactive` command on the Kubernetes pod via the WebSocket stream with `tty=True`. Keystrokes are relayed frame-by-frame and rendered in the browser terminal emulator.

---

## 4. Database Schema Specifications

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

---

## 5. Architectural Benefits

1.  **Infinite Extensibility**: Developers can support new coding agents (e.g., `swe-agent`, `open-interpreter`) simply by registering a new runtime manifest, with **zero changes to the Python backend**.
2.  **Explicit Secret Boundaries**: Outpost dictates what secrets are injected via the `variables` declaration, preventing the coding agent from scanning the host container for undeclared tokens.
3.  **Audited Shell Access**: High-grade logging intercepts all inputs passing through the PTY gateway, satisfying enterprise compliance.
