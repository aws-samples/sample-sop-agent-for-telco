# ANPA — Autonomous Network Provisioning Agent

Day 0 bare-metal provisioning and EKS Hybrid cluster lifecycle management for 5G telco sites.

## Overview

ANPA automates the provisioning of bare-metal servers and EKS Hybrid Nodes clusters at telco edge sites. It integrates with Tinkerbell for OS provisioning, AWS SSM for hybrid node registration, and manages the full lifecycle from hardware discovery to cluster readiness.

## Prerequisites

- EKS management cluster with ArgoCD
- Tinkerbell stack deployed (optional, for bare-metal provisioning)
- AWS IAM role with permissions for EKS, SSM, and EC2
- `anra-common` chart installed (CRDs)

## Install

```bash
# Install shared CRDs first
helm install anra-common oci://public.ecr.aws/eks-hybrid-telco/helm/anra-common -n anra-system --create-namespace

# Install ANPA
helm install anpa oci://public.ecr.aws/eks-hybrid-telco/helm/anpa -n anpa-system --create-namespace \
  --set image.repository=<ECR_URI> \
  --set aws.region=us-west-2 \
  --set secrets.bmcUsername=admin \
  --set secrets.bmcPassword=<PASSWORD>
```

## Custom Resources

| CRD | Scope | Description |
|-----|-------|-------------|
| `Site` | Cluster | Physical site topology (from anra-common) |
| `Cluster` | Cluster | EKS cluster definition (from anra-common) |
| `HardwareInventory` | Cluster | Discovered bare-metal servers |
| `ProvisioningRequest` | Namespaced | Request to provision a new cluster |

## Configuration

See [values.yaml](./values.yaml) for all configurable parameters.

### Key Parameters

| Parameter | Description | Default |
|-----------|-------------|---------|
| `aws.region` | AWS region for EKS/SSM | `us-west-2` |
| `aws.eks.kubernetesVersion` | Target K8s version | `1.31` |
| `tinkerbell.enabled` | Enable Tinkerbell integration | `true` |
| `inventorySync.enabled` | Enable periodic hardware discovery | `true` |
| `inventorySync.schedule` | Cron schedule for discovery | `*/30 * * * *` |
| `osImages.profiles` | OS image profiles per node role | See values.yaml |
