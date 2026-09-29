# Deploy the Free5GC Core on the Workshop-v3 Cluster

## Overview
Configure the CloudFormation-provisioned EKS cluster, install Multus, verify gtp5g, and deploy the pinned Free5GC v4.2.3 and PacketRusher charts. This replaces the Open5GS deployment path.

## Parameters

- **stack_name** (required): CloudFormation stack created by the Day-0 SOP.
- **aws_region** (required): AWS Region containing the stack and EKS cluster.
- **namespace** (optional, default: `free5gc`): Kubernetes namespace for Free5GC and PacketRusher.

**Constraints for parameter acquisition:**
- If all required parameters are already provided, You MUST proceed to the Steps
- If any required parameters are missing, You MUST ask for them before proceeding
- When asking for parameters, You MUST request all parameters in a single prompt
- When asking for parameters, You MUST use the exact parameter names as defined

## Prerequisites
- The CloudFormation Day-0 SOP completed successfully.
- Commands run from the workshop-v3 repository on the bastion.
- The bastion role can update kubeconfig and use SSM on worker nodes.

## Steps

### 1. Configure the cluster networking
Install pinned Multus and metrics-server components and verify gtp5g on workers.

```bash
export STACK_NAME="${STACK_NAME:?Set STACK_NAME from stack_name}"
export CLUSTER_NAME="${CLUSTER_NAME:-eks-$STACK_NAME}"
export AWS_DEFAULT_REGION="${AWS_DEFAULT_REGION:?Set AWS_DEFAULT_REGION from aws_region}"
bash scripts/free5gc/02-configure-cluster.sh
```

**Expected**: All worker nodes are Ready, the Multus daemonset is available, and each worker reports `GTP5G_LOADED_OK`.

**Constraints:**
- You MUST stop if gtp5g is not confirmed because the Free5GC UPF cannot start without the compatible kernel module.
- You MUST use the pinned Multus and gtp5g versions because the chart and interface plan were validated together.

### 2. Deploy Free5GC and PacketRusher
Install the bundled chart archives into the dedicated namespace.

```bash
export NAMESPACE="${NAMESPACE:-free5gc}"
bash scripts/free5gc/03-deploy-workloads.sh
```

**Expected**: Free5GC core, MongoDB, WebUI, UPF, and PacketRusher pods reach Running state; the PacketRusher log reports a PDU session and UE address.

**Constraints:**
- You MUST use the bundled `free5gc-0.0.2.tgz` and `packetrusher-0.0.3.tgz` archives rather than downloading mutable charts.
- You MUST NOT install Open5GS because workshop-v3 has one authoritative 5G core.
- If subscriber reconciliation fails, You MUST stop rather than hiding the failure because the E2E validation depends on the expected slice.

### 3. Record the deployment baseline
Capture resources and chart versions for later monitoring validation.

```bash
helm list -n "${NAMESPACE:-free5gc}"
kubectl get pods -n "${NAMESPACE:-free5gc}" -o wide
kubectl get network-attachment-definitions -n "${NAMESPACE:-free5gc}"
```

**Expected**: The two releases are present and all expected N2/N3/N4/N6 attachments exist.

**Constraints:**
- You MUST save the output with the dry-run record.
- You MUST NOT proceed to SOP 2 while any Free5GC or PacketRusher container is unready because end-to-end results would not represent a healthy deployment baseline.

## Examples
For a stack named `telco-dryrun-01`, set `STACK_NAME=telco-dryrun-01`, `CLUSTER_NAME=eks-telco-dryrun-01`, and `NAMESPACE=free5gc`.

## Troubleshooting
If the UPF fails, verify gtp5g version `0.9.15` and the N3/N4/N6 interfaces. If the PDU session fails, inspect the SMF/UPF PFCP logs and rerun the idempotent subscriber-slice helper.
