# Deploy the Free5GC Core on the Workshop-v3 Cluster

## Overview
Use the Kubernetes context prepared by Workshop Studio to install Multus and deploy the pinned Free5GC v4.2.3 and PacketRusher charts. This SOP does not discover or reconfigure the EKS cluster because CloudFormation owns the workshop infrastructure.

## Parameters

- **namespace** (optional, default: `free5gc`): Kubernetes namespace for Free5GC and PacketRusher.

**Constraints for parameter acquisition:**
- If all required parameters are already provided, You MUST proceed to the Steps
- If any required parameters are missing, You MUST ask for them before proceeding
- When asking for parameters, You MUST request all parameters in a single prompt
- When asking for parameters, You MUST use the exact parameter names as defined

## Prerequisites
- Workshop Studio provisioning completed successfully.
- Commands run from the workshop-v3 repository on the bastion.
- The current Kubernetes context targets the workshop EKS cluster.
- CloudFormation installed the pinned gtp5g module on every worker.

## Steps

### 1. Validate the current Kubernetes context
Confirm the preconfigured context is reachable and all workers are Ready before changing Kubernetes resources.

```bash
export NAMESPACE="${NAMESPACE:-free5gc}"
CURRENT_CONTEXT="$(kubectl config current-context 2>/dev/null || true)"
test -n "$CURRENT_CONTEXT"
printf 'Using Kubernetes context: %s\n' "$CURRENT_CONTEXT"
kubectl get --raw=/readyz >/dev/null
kubectl auth can-i get nodes | grep -qx yes
kubectl wait --for=condition=Ready nodes --all --timeout=600s
```

**Expected**: A non-empty context is displayed, the API readiness check succeeds, authorization returns `yes`, and every worker is Ready.

**Constraints:**
- You MUST use the context that is current when this SOP starts.
- You MUST NOT run `aws eks update-kubeconfig` because Workshop Studio already selected the participant cluster and changing context could target a different environment.
- You MUST stop if the context is empty, unreachable, unauthorized, or has an unready worker because the deployment must not continue against an unknown or unhealthy cluster.

### 2. Configure Kubernetes networking
Install the pinned Multus and metrics-server components on the current cluster.

```bash
bash scripts/free5gc/02-configure-cluster.sh
```

**Expected**: The Multus daemonset and metrics-server deployment become available on the current cluster.

**Constraints:**
- You MUST use the pinned Multus version because the chart and interface plan were validated together.
- You MUST NOT use EC2 or SSM to repair worker hosts because missing host prerequisites are a Workshop Studio provisioning defect.

### 3. Deploy Free5GC and PacketRusher
Verify gtp5g through Kubernetes, then install the bundled chart archives into the dedicated namespace.

```bash
bash scripts/free5gc/03-deploy-workloads.sh
```

**Expected**: Every worker reports the gtp5g module loaded; Free5GC core, MongoDB, WebUI, UPF, and PacketRusher pods reach Running state; the PacketRusher log reports a PDU session and UE address.

**Constraints:**
- You MUST pass `timeout=480` to run_command for this step because the script includes deliberate pod-stabilisation sleeps totalling approximately 5 minutes.
- You MUST stop if gtp5g is not confirmed because the Free5GC UPF cannot start without the compatible kernel module.
- You MUST use the bundled `free5gc-0.0.2.tgz` and `packetrusher-0.0.3.tgz` archives rather than downloading mutable charts.
- You MUST NOT install Open5GS because workshop-v3 has one authoritative 5G core.
- If subscriber reconciliation fails, You MUST stop rather than hiding the failure because the E2E validation depends on the expected slice.

### 4. Record the deployment baseline
Capture resources and chart versions for later monitoring validation.

```bash
helm list -n "$NAMESPACE"
kubectl get pods -n "$NAMESPACE" -o wide
kubectl get network-attachment-definitions -n "$NAMESPACE"
```

**Expected**: The two releases are present and all expected N2/N3/N4/N6 attachments exist.

**Constraints:**
- You MUST retain the output with the dry-run record.
- You MUST NOT proceed to SOP 2 while any Free5GC or PacketRusher container is unready because end-to-end results would not represent a healthy deployment baseline.

## Examples
Run the SOP directly after Workshop Studio provisioning. The default invocation uses the current Kubernetes context and namespace `free5gc`; no stack name, cluster name, or AWS Region input is required.

## Troubleshooting
If the current context is incorrect, stop and report a Workshop Studio provisioning problem rather than selecting another cluster from this SOP. If the UPF fails, verify gtp5g version `0.9.15` and the N3/N4/N6 interfaces. If the PDU session fails, inspect the SMF/UPF PFCP logs and rerun the idempotent subscriber-slice helper.
