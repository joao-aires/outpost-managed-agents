# Blueprint: Configurable & Agent-Agnostic Sandboxes

To support running various coding agents inside Outpost sandboxes (such as **Claude Code**, **OpenCode**, **Cursor-agent**, and **Antigravity-cli**) while remaining **agent-agnostic** and fully customizable by the user, we will introduce a **Coding Agent Specification Schema**.

This allows users to register custom coding runtimes and have Outpost spin them up with the appropriate secrets, volumes, and execution commands.

---

## 1. Architectural Strategy

We will split the lifecycle of the coding agent sandboxes into three layers:

1.  **Specification Registry**: A database table and REST API (`/v1/coding-agents`) allowing users to define how a coding agent is installed, run, and configured.
2.  **Hybrid Provisioning**:
    *   **Pre-baked (Defaults)**: Common CLIs (Claude Code, OpenCode, `agy`, Cursor) will be pre-compiled into our core Sandbox Docker image (`Dockerfile.sandbox`) to preserve the `<150ms` start time.
    *   **On-Demand (Dynamic)**: Custom user-defined agents are installed just-in-time when the Pod boots using a startup shell script defined in the spec.
3.  **Secure Egress & Ingress Injection**: Map environment keys (like `ANTHROPIC_API_KEY` or `CURSOR_API_KEY`) and state caches (like `~/.claude/` session directories) dynamically at Pod startup.

```
 [User API Request] ──────> Defines Agent Profile (using config.coding_agent = "claude-code")
                                   │
                                   ▼
 [Outpost Control Plane] ──> Resolves CodingAgentSpec in Database
                                   │
                                   ├─ Injects Env Secrets (e.g. ANTHROPIC_API_KEY)
                                   ├─ Sets up Persistent Directory Mounts
                                   ▼
 [Kubernetes Cluster] ───> Spawns Pod Sandbox
                                   │ (Runs spec.installer if not pre-baked)
                                   ▼
                         [ Active Coding Agent CLI Loop ]
```

---

## 2. Configuration & Specification Schema

We define the Pydantic schema representing a configurable coding agent:

```python
from pydantic import BaseModel, Field
from typing import Dict, List, Optional

class CodingAgentSpec(BaseModel):
    id: str = Field(..., description="Unique slug identifier (e.g., 'claude-code')")
    name: str = Field(..., description="Human readable name")
    description: Optional[str] = None
    
    # Installation & Boot
    installer_cmd: Optional[str] = Field(
        None, 
        description="Shell script to install the CLI on-demand (e.g. 'curl -fsSL https://claude.ai/install.sh | bash')"
    )
    entrypoint_cmd: str = Field(
        ..., 
        description="Core command to start the agent (e.g. 'claude')"
    )
    
    # Environments & Secrets Configuration
    required_env_keys: List[str] = Field(
        default_factory=list,
        description="List of environment keys to inject from control plane secrets (e.g., ['ANTHROPIC_API_KEY'])"
    )
    default_env_vars: Dict[str, str] = Field(
        default_factory=dict,
        description="Default non-secret environment variables (e.g. {'CI': '1'})"
    )
    
    # State Persistence Configuration
    cache_paths: List[str] = Field(
        default_factory=list,
        description="List of directory paths inside the container to persist using volumes (e.g., ['/home/agent/.claude'])"
    )
```

---

## 3. Specifications for Default Supported Agents

These default specs will be loaded into the database during startup migration:

### 3.1 Claude Code (`claude-code`)
*   **Target CLI**: `claude` (Anthropic's terminal agent)
*   **API Credentials**: `ANTHROPIC_API_KEY` or OAuth flow
*   **Specification**:
    ```json
    {
      "id": "claude-code",
      "name": "Claude Code",
      "entrypoint_cmd": "claude",
      "installer_cmd": "curl -fsSL https://claude.ai/install.sh | bash",
      "required_env_keys": ["ANTHROPIC_API_KEY"],
      "default_env_vars": {
        "SHELL": "/bin/bash",
        "CI": "1"
      },
      "cache_paths": ["/home/agent/.claude"]
    }
    ```

### 3.2 OpenCode (`opencode`)
*   **Target CLI**: `opencode` (Open source agent runtime)
*   **API Credentials**: `OPENCODE_API_KEY`
*   **Specification**:
    ```json
    {
      "id": "opencode",
      "name": "OpenCode CLI",
      "entrypoint_cmd": "opencode run",
      "installer_cmd": "npm install -g @opencode/cli",
      "required_env_keys": ["OPENCODE_API_KEY", "OPENAI_API_KEY"],
      "cache_paths": ["/home/agent/.config/opencode"]
    }
    ```

### 3.3 Antigravity CLI (`antigravity-cli`)
*   **Target CLI**: `agy` (Antigravity's terminal companion agent)
*   **API Credentials**: `ANTHROPIC_API_KEY` / `GEMINI_API_KEY`
*   **Specification**:
    ```json
    {
      "id": "antigravity-cli",
      "name": "Antigravity CLI",
      "entrypoint_cmd": "agy",
      "installer_cmd": "curl -fsSL https://antigravity.google/install.sh | bash",
      "required_env_keys": ["ANTHROPIC_API_KEY", "GEMINI_API_KEY"],
      "cache_paths": ["/home/agent/.gemini/antigravity-cli"]
    }
    ```

### 3.4 Cursor Agents (`cursor-agents`)
*   **Target CLI**: `cursor-agent`
*   **API Credentials**: `CURSOR_API_KEY`
*   **Specification**:
    ```json
    {
      "id": "cursor-agent",
      "name": "Cursor Agent",
      "entrypoint_cmd": "cursor-agent",
      "installer_cmd": "npm install -g @cursor/agent",
      "required_env_keys": ["CURSOR_API_KEY"],
      "cache_paths": ["/home/agent/.cursor"]
    }
    ```

---

## 4. Implementation Steps

1.  **Database Migration**: Add a `coding_agents` table to persist specifications:
    ```sql
    CREATE TABLE coding_agents (
        id VARCHAR(100) PRIMARY KEY,
        name VARCHAR(255) NOT NULL,
        description TEXT,
        installer_cmd TEXT,
        entrypoint_cmd TEXT NOT NULL,
        required_env_keys JSON,
        default_env_vars JSON,
        cache_paths JSON
    );
    ```
2.  **Expose Configuration REST API**:
    *   `GET /v1/coding-agents`: Returns the list of registered specs.
    *   `POST /v1/coding-agents`: Inserts a new custom specification.
3.  **Update Sandbox Bootstrapping**:
    When provisioning the sandbox, the `BaseSandboxDriver` will read the selected agent's `cache_paths` and map Kubernetes `volumeMounts` dynamically so that login states persist.
4.  **UI Updates**: Add a dropdown selectors in the **New Agent Profile** modal in the Admin Console so users can toggle between `Claude Code`, `OpenCode`, or their own registered custom runtime configurations.
