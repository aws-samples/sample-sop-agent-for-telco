# ANO Platform

Full autonomous network operations platform for 5G RAN/Core on Amazon EKS Hybrid Nodes.

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                   ANO Platform                          │
├───────────────┬───────────────┬─────────────────────────┤
│     ANPA      │     ANDA      │          ANRA           │
│   (Day 0)     │   (Day 1)     │        (Day 2)          │
│  Provisioning │  Deployment   │  Monitoring & Remediation│
├───────────────┴───────────────┴─────────────────────────┤
│                  anra-common (CRDs)                      │
└─────────────────────────────────────────────────────────┘
```

| Agent | Responsibility | Deploys To |
|-------|---------------|------------|
| **ANPA** | Bare-metal provisioning, EKS cluster creation, OS imaging | Management cluster |
| **ANDA** | NF deployment via ArgoCD, upgrade orchestration (drain → sync → verify) | Management cluster |
| **ANRA** | Autonomous monitoring, alarm correlation, SOP execution | Workload cluster(s) |

## Lifecycle Management

> **Design principle:** The management plane bootstraps itself. Control plane agents
> are upgraded carefully. Workload NFs use standard deployment tooling (ArgoCD).

### What manages what

```
Bootstrap script (runs once)
  ├── ArgoCD           ← Helm install on mgmt cluster
  ├── ANPA (Day 0)     ← Helm install on mgmt cluster
  ├── ANDA (Day 1)     ← Helm install on mgmt cluster
  └── ANRA (Day 2)     ← Helm install on workload cluster(s)

After bootstrap:
  ANPA/ANDA upgrades   ← helm upgrade with manual approval (CI pipeline)
  ANRA upgrades        ← Self-updating agent (pulls from ECR, maintenance windows)
  5G NF deployments    ← ArgoCD, orchestrated by ANDA (drain → sync → verify)
```

### Why not ArgoCD for agent LCM?

| Concern | Impact |
|---------|--------|
| Edge sites lose WAN connectivity | ANRA must operate independently — can't depend on remote ArgoCD |
| NF upgrades are stateful | AMF holds UE sessions; ArgoCD can't orchestrate drain/migrate/verify |
| Provisioning is event-driven | Site commissioning starts from a work order, not a Git push |
| Control plane is high-risk | Auto-syncing ANPA/ANDA from Git could deprovision servers |

### Agent upgrade paths

| Agent | Mechanism | Trigger | Rollback |
|-------|-----------|---------|----------|
| ANPA | `helm upgrade` | CI pipeline + manual approval | `helm rollback` |
| ANDA | `helm upgrade` | CI pipeline + manual approval | `helm rollback` |
| ANRA | Self-update CronJob | ECR image push + maintenance window | Auto-rollback on failed health check |
| NFs | ArgoCD sync | ANDA `DeploymentPlan` CR | ANDA orchestrates rollback sequence |

## Quick Start

### Bootstrap (full platform)

```bash
./bootstrap.sh \
  --mgmt-context mgmt-cluster \
  --workload-context site-002-workload,site-003-workload \
  --values my-site-values.yaml \
  --registry 123456789.dkr.ecr.us-west-2.amazonaws.com
```

### Bootstrap (incremental adoption)

```bash
# Day 0 only — start with provisioning
./bootstrap.sh \
  --mgmt-context mgmt-cluster \
  --values provisioning-values.yaml \
  --skip-anda --skip-anra

# Add Day 2 later when workload cluster is ready
./bootstrap.sh \
  --mgmt-context mgmt-cluster \
  --workload-context site-002-workload \
  --values site-002-values.yaml \
  --skip-argocd --skip-anpa --skip-anda
```

### Upgrade agents

```bash
# ANPA/ANDA: manual helm upgrade with approval gate
helm upgrade anpa oci://public.ecr.aws/eks-hybrid-telco/helm/anpa \
  --version 0.3.0 -n anpa-system -f values.yaml

# ANRA: push new image to ECR — self-update picks it up automatically
docker push 123456.dkr.ecr.us-west-2.amazonaws.com/anra:0.3.0
```

## Version Compatibility

All charts are version-locked during early development:

| anra-common | anpa | anda | anra | Status |
|-------------|------|------|------|--------|
| 0.2.0 | 0.2.0 | 0.2.0 | 0.2.0 | Current |

## Sub-Chart Documentation

- [ANPA — Provisioning Agent](../anpa/README.md)
- [ANDA — Deployment Agent](../anda/README.md)
- [ANRA — Remediation Agent](../../helm-charts/anra/)
