# Revised Blueprint: Declarative Sandbox Agent Interface (SAI)

Based on your feedback, we have refactored the design to make the sandboxes fully flexible. 

Outpost will **not** contain any hardcoded logic or models for specific coding agents. Instead, the interface between Outpost and any coding agent is defined by a **Declarative Runtime Manifest** (`AgentRuntimeManifest`).

Outpost acts as a **generic container scheduler, secret vault, and interactive terminal relay (PTY)** that executes the lifecycle hooks defined in the agent's manifest.

---

## 1. The Declarative Manifest Interface (`agent-runtime.yaml`)

Every coding agent (whether it is Claude Code, OpenCode, or a custom developer script) is defined by a YAML manifest. This manifest is the exact interface Outpost uses to create and run the agent.

```yaml
# Example: docs/runtimes/claude-code.yaml
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
  # Paths that must persist across container restarts (mounted via K8s volumes)
  persistent_paths:
    - name: "claude-cache"
      mount_path: "/home/agent/.claude"

# 2. Variable & Secret Definitions (Injected by Outpost at startup)
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

## 2. Refactored Outpost Control Plane Flow

Under this model, the Outpost backend implements a generic **Lifecycle Executor Engine** instead of writing custom driver classes for each agent:

```
                  [ USER START SESSION REQUEST ]
                                │ (Passes AgentRuntimeManifest)
                                ▼
 ┌─────────────────────────────────────────────────────────────┐
 │                    Outpost Control Plane                    │
 └──────────────────────────────┬──────────────────────────────┘
                                │
                                ├─ 1. Reads 'sandbox' requirements
                                ├─ 2. Resolves & encrypts variables/secrets
                                ├─ 3. Provisions generic K8s Pod + PVC Mounts
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

### 2.1 Bootstrapping Phase (`setup`)
When a session is initiated, Outpost provisions a container running the specified `default_image`. It then issues the `lifecycle.setup` commands inside the container using the Kubernetes exec API. This allows the sandbox to pull and set up its own tools (e.g. executing `npm install` or downloading executables).

### 2.2 Interactive PTY Relay (`run_interactive`)
To support terminal-based coding agents like Claude Code, the Outpost frontend needs to act as a terminal client. 
1. Outpost backend opens a Pseudo-Terminal (PTY) by executing the `run_interactive` command on the Kubernetes pod via the WebSocket stream.
2. The user's inputs in the operations console are sent raw over the WebSocket to the PTY stdin.
3. The raw ANSI terminal outputs (colors, interactive layouts, selections) are streamed back to the browser and rendered using **Xterm.js**.

---

## 3. Benefits of this Interface

1.  **Infinite Extensibility**: Developers can support new coding agents (e.g., `swe-agent`, `devika`, `open-interpreter`) simply by dropping a new YAML manifest file into the `runtimes/` folder, with **zero changes to the Python backend**.
2.  **Explicit Secret Boundaries**: Outpost dictates what secrets are injected via the `variables` declaration, preventing the coding agent from scanning the host container for undeclared tokens.
3.  **Unified Frontend Console**: The Admin Dashboard's terminal becomes a standard PTY client, allowing the developer to interact with *any* command-line agent seamlessly.
