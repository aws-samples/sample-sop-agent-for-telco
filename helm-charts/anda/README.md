# ANDA — Autonomous Network Deployment Agent

Day 1 network function deployment and validation for 5G RAN/Core on EKS Hybrid clusters.

## Overview

ANDA automates the deployment of 5G network functions (srsRAN gNB, Open5GS core) onto provisioned EKS Hybrid clusters. It integrates with ArgoCD for GitOps-driven deployments, performs pre-flight validation, and verifies NF health post-deployment.

## Prerequisites

- EKS management cluster with ArgoCD installed
- `anra-common` chart installed (shared CRDs)
- Clusters provisioned by ANPA (Site/Cluster CRs available)
- Git repository for GitOps manifests

## Install

```bash
# Install shared CRDs first (if not already installed)
helm install anra-common oci://public.ecr.aws/eks-hybrid-telco/helm/anra-common -n anra-system --create-namespace

# Install ANDA
helm install anda oci://public.ecr.aws/eks-hybrid-telco/helm/anda -n anda-system --create-namespace \
  --set image.repository=<ECR_URI> \
  --set argocd.serverUrl=https://argocd.example.com \
  --set gitops.repoUrl=https://github.com/org/telco-gitops.git \
  --set secrets.gitToken=<TOKEN>
```

## Custom Resources

| CRD | Scope | Description |
|-----|-------|-------------|
| `NFDeployment` | Namespaced | Individual NF deployment instance |
| `DeploymentPlan` | Namespaced | Orchestrated multi-NF deployment plan |

## Deployment Flow

```
DeploymentPlan CR created
  → Pre-flight validation (node ready, resources available)
  → Resolve dependency order
  → Create ArgoCD Applications per NF
  → Monitor sync + health status
  → Post-deploy validation (pod running, NF registered)
  → Update status
```

## Configuration

See [values.yaml](./values.yaml) for all configurable parameters.

### Key Parameters

| Parameter | Description | Default |
|-----------|-------------|---------|
| `argocd.enabled` | Enable ArgoCD integration | `true` |
| `argocd.namespace` | ArgoCD namespace | `argocd` |
| `gitops.repoUrl` | GitOps repository URL | `""` |
| `gitops.branch` | Git branch | `main` |
| `nfCatalog.*` | NF chart references | See values.yaml |
| `validation.preflight.enabled` | Pre-deploy checks | `true` |
| `validation.postDeploy.enabled` | Post-deploy checks | `true` |
| `networkPolicy.enabled` | Restrict egress | `true` |
