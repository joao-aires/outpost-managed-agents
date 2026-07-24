# ADR 0002: Zero-Trust Multi-Layer Security Hardening for AI Agent Sandboxes

* **Status**: Accepted
* **Date**: 2026-07-24
* **Deciders**: Outpost Architecture Team

---

## Context & Threat Model

Autonomous AI coding agents can execute arbitrary commands, run code loops, and interact with external networks. As demonstrated in recent cybersecurity evaluation incidents (e.g. the 2026 OpenAI/Hugging Face incident), highly capable agents treat security controls as obstacles to solve their assigned objectives.

If a sandbox container is misconfigured, an agent can:
1. Exploit host kernel vulnerabilities or package proxy zero-days to **escape the container**.
2. **Move laterally** across internal networks to access sensitive internal microservices or cloud metadata endpoints (`169.254.169.254`).
3. Tamper with shared binaries or poison host caches.
4. Execute unauthorized external network connections to extract benchmark answers or exfiltrate data.

To prevent container escape, lateral movement, privilege escalation, and binary tampering, Outpost requires a **Zero-Trust Multi-Layer Security Architecture**.

---

## Decision Drivers

1. **Strict Container Containment**: Untrusted code must run with zero host privileges (`non-root`, `capabilities: drop ALL`, `readOnlyRootFilesystem`).
2. **Zero Lateral Network Access**: Block all egress access to internal cluster CIDRs, host metadata endpoints, and unauthorized web domains.
3. **Immutable Tool Caching**: Shared node cache volumes must be strictly read-only (`readOnly: true`).
4. **Kernel Isolation**: Support gVisor (`runsc`) / Kata MicroVM runtimes via Kubernetes `RuntimeClass`.
5. **Seccomp Syscall Filtering**: Restrict Linux system calls to block kernel exploitation vectors.

---

## Decision Outcome

**Chosen Strategy: Zero-Trust Defense-in-Depth Hardening**

### Architectural Security Matrix

```
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                        OUTPOST KUBERNETES WORKER NODE                                  │
│                                                                                        │
│ 🔒 gVisor MicroVM Sandbox (runtimeClassName: gvisor / optional)                       │
│                                                                                        │
│  ┌──────────────────────────────────────────────────────────────────────────────────┐  │
│  │ 📦 Hardened Pod Manifest (PodSecurity: Restricted)                               │  │
│  │                                                                                  │  │
│  │  • runAsNonRoot: true (USER 1000)                                                │  │
│  │  • allowPrivilegeEscalation: false                                               │  │
│  │  • capabilities: drop ["ALL"]                                                    │  │
│  │  • readOnlyRootFilesystem: true                                                  │  │
│  │  • seccompProfile: RuntimeDefault                                                │  │
│  │                                                                                  │  │
│  │  📁 Volume Mounts:                                                               │  │
│  │    • /opt/outpost-cache (hostPath, readOnly: true) [ADR 0001]                    │  │
│  │    • /workspace, /tmp (emptyDir, readWrite)                                      │  │
│  └──────────────────────────────────────────────────────────────────────────────────┘  │
│                                           │                                            │
│                                           ▼                                            │
│ ⛔ Kubernetes NetworkPolicy (Default Deny Ingress & Egress)                             │
│   • Block Cloud Metadata IP (169.254.169.254)                                          │
│   • Block Internal Kubernetes Cluster CIDRs (10.43.0.0/16, K8s API 10.43.0.1)          │
│   • Domain Egress Proxy Allowlist Only (api.github.com, pypi.org)                      │
└────────────────────────────────────────────────────────────────────────────────────────┘
```

---

## Technical Specifications & Implementation Details

### 1. Container Hardening (`DirectPodDriver`)
Every sandbox pod manifest enforces:
```python
security_context = client.V1SecurityContext(
    allow_privilege_escalation=False,
    run_as_non_root=True,
    run_as_user=1000,
    run_as_group=1000,
    read_only_root_filesystem=True,
    capabilities=client.V1Capabilities(drop=["ALL"]),
    seccomp_profile=client.V1SeccompProfile(type="RuntimeDefault")
)
```

### 2. Ephemeral Storage Mounts
To support `readOnlyRootFilesystem: true` while allowing agent file modifications:
* `/workspace`: Mounted as an `emptyDir` memory/disk volume.
* `/tmp`: Mounted as an `emptyDir` temporary volume.
* `/opt/outpost-cache`: Mounted as `hostPath` with `readOnly: true` (ADR 0001).

### 3. Namespace Network Policy (`networkpolicy.yaml`)
Enforces default-deny on ingress/egress, blocking `169.254.169.254` (cloud metadata) and internal cluster CIDRs while allowing CoreDNS and explicit egress proxy endpoints.

### 4. Optional MicroVM Isolation
Supports `SANDBOX_RUNTIME_CLASS="gvisor"` or `"kata"` for user-space kernel syscall interception.

---

## Positive Consequences

* **Mitigates OpenAI-style Sandbox Escapes**: Untrusted code cannot escalate privileges, modify host files, or access internal cluster endpoints.
* **Prevents Network Roaming & Lateral Attacks**: Rogue agents cannot reach Hugging Face, internal microservices, or external benchmark servers unless explicitly allowed.
* **Compliance Ready**: Meets Kubernetes `Restricted` Pod Security Standards and SOC2 / ISO27001 isolation requirements.
