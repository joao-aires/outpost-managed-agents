# Outpost Managed Agents — Production Helm Chart Deployment Guide

Outpost Managed Agents provides a production-ready **Helm v3 Chart** located in `charts/outpost-managed-agents/`.

---

## 🚀 Quick Start

### 1. Prerequisites
* Kubernetes Cluster (1.26+) or local Kubernetes (Rancher Desktop, minikube, k3s, EKS, GKE, AKS)
* `helm` v3.8+ installed
* `kubectl` configured with cluster access

### 2. Install Chart locally or in production

```bash
# Add chart and deploy to 'outpost-system' namespace
helm upgrade --install outpost-cma charts/outpost-managed-agents \
  --namespace outpost-system \
  --create-namespace \
  --set config.sandboxDriver=direct \
  --set config.llmProvider=ollama \
  --set config.llmBaseUrl="http://host.docker.internal:11434"
```

---

## ⚙️ Key Configuration Parameters (`values.yaml`)

| Parameter | Description | Default |
| :--- | :--- | :--- |
| `replicaCount` | Outpost Control Plane Replicas | `1` |
| `image.repository` | Outpost Control Plane Docker Image | `outpost-managed-agents` |
| `image.tag` | Outpost Image Tag | `latest` |
| `config.sandboxDriver` | Sandbox execution backend (`direct`, `sigs-sandbox`, `mock`) | `direct` |
| `config.kubernetesNamespace` | Namespace where agent pods run | `agent-sandboxes` |
| `config.sandboxImage` | Sandbox pod runtime container image | `outpost-sandbox:latest` |
| `config.warmPoolSize` | Number of pre-warmed sandbox pods | `3` |
| `config.llmProvider` | Inference provider (`anthropic`, `ollama`) | `anthropic` |
| `config.llmBaseUrl` | Custom base URL for Ollama / local LLM | `""` |
| `secrets.anthropicApiKey` | Anthropic API Key | `""` |
| `ingress.enabled` | Enable Ingress resource for external API access | `false` |
| `autoscaling.enabled` | Enable HorizontalPodAutoscaler | `false` |

---

## 🔍 Verification Commands

```bash
# Check Helm release status
helm status outpost-cma -n outpost-system

# Check deployed control plane pods
kubectl get pods -n outpost-system

# Check pre-warmed sandbox pods
kubectl get pods -n agent-sandboxes
```
