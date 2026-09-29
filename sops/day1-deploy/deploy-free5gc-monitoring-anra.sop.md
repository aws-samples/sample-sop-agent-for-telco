# Deploy Free5GC Monitoring and ANRA

## Overview
Deploy pinned Prometheus, Alertmanager, and Grafana configuration around a validated Free5GC service, then install ANDA and ANRA in manual-approval mode. ANPA is intentionally excluded because CloudFormation owns Day-0 infrastructure.

## Parameters

- **stack_name** (required): CloudFormation stack name used to derive the EKS cluster.
- **aws_region** (required): AWS Region containing the EKS cluster.
- **bedrock_region** (optional, default: `us-west-2`): AWS Region used for Amazon Bedrock inference.
- **agent_image_repository** (required): Registry/repository containing the tested workshop-v3 image.
- **agent_image_tag** (required): Immutable image tag associated with the workshop-v3 source revision.
- **anra_password** (optional): Dashboard password; when omitted, the deployment script generates one and stores it in `${HOME}/anra-admin-password` with owner-only permissions.

**Constraints for parameter acquisition:**
- If all required parameters are already provided, You MUST proceed to the Steps
- If any required parameters are missing, You MUST ask for them before proceeding
- When asking for parameters, You MUST request all parameters in a single prompt
- When asking for parameters, You MUST use the exact parameter names as defined
- You MUST reject `latest` as `agent_image_tag` because a dry run requires an immutable image baseline

## Prerequisites
- SOP 1 deployed Free5GC and SOP 2 passed end to end.
- The image contains `configs/free5gc-monitoring`, `alarm-references/free5gc.yaml`, the SOPs, scripts, and bundled charts.
- The EKS worker role or pod identity can invoke the selected Amazon Bedrock model.

## Steps

### 1. Verify the monitoring contract
Check every pinned runtime asset before changing the cluster.

```bash
test -f configs/free5gc-monitoring/kube-prometheus-stack-values.yaml
test -f configs/free5gc-monitoring/free5gc-alert-rules.yaml
test -f configs/free5gc-monitoring/anra-values.yaml
test -f configs/free5gc-monitoring/dashboards/free5gc-core-overview.json
test -f alarm-references/free5gc.yaml
test -f scripts/send-free5gc-test-alert.py
! grep -R '/api/webhooks/alertmanager' configs/free5gc-monitoring configs/alertmanager
```

**Expected**: All assets exist and no configuration references the obsolete webhook path.

**Constraints:**
- You MUST stop if an asset is missing because ad hoc downloads would invalidate the recorded release candidate.
- You MUST use `/api/alertmanager` because that is the implemented ANRA route.

### 2. Deploy monitoring, ANDA, and ANRA
Run the deterministic installer with the immutable image reference.

```bash
export STACK_NAME="${STACK_NAME:?Set STACK_NAME from stack_name}"
export CLUSTER_NAME="${CLUSTER_NAME:-eks-$STACK_NAME}"
export AWS_DEFAULT_REGION="${AWS_DEFAULT_REGION:?Set AWS_DEFAULT_REGION from aws_region}"
export BEDROCK_REGION="${BEDROCK_REGION:-us-west-2}"
export AGENT_IMAGE_REPOSITORY="${AGENT_IMAGE_REPOSITORY:?Set AGENT_IMAGE_REPOSITORY from agent_image_repository}"
export AGENT_IMAGE_TAG="${AGENT_IMAGE_TAG:?Set AGENT_IMAGE_TAG from agent_image_tag}"
test "$AGENT_IMAGE_TAG" != latest
if test -n "${ANRA_PASSWORD:-}"; then export ANRA_PASSWORD; fi
bash scripts/free5gc/04-deploy-monitoring-anra.sh
```

**Expected**: Prometheus, Alertmanager, Grafana, ANDA, and ANRA are Ready; the script reports `ANPA=skipped`.

**Constraints:**
- You MUST deploy the monitoring stack separately from the ANRA chart because the ANRA chart is agent-only.
- You MUST NOT install ANPA because workshop-v3 uses CloudFormation for infrastructure.
- You MUST configure both the remediation target and watched namespace as `free5gc`; these are independent settings.

### 3. Verify effective ANRA configuration
Confirm the environment and rendered agent configuration match the workshop contract.

```bash
kubectl get deployment anra -n anra-system -o json | jq -er '
  [.spec.template.spec.containers[0].env[] | select(
    .name == "APPROVAL_MODE" or
    .name == "DEFAULT_NF_NAMESPACE" or
    .name == "DEFAULT_NF_VENDOR" or
    .name == "DEFAULT_RAN_NAMESPACE" or
    .name == "ALERTMANAGER_URL") | "\(.name)=\(.value)"] | sort | .[]'
kubectl get configmap anra-config -n anra-system -o jsonpath='{.data.agent-config\.yaml}' | grep -E 'alarm_references:|free5gc|namespaces:'
```

**Expected**: Approval is `manual`, core namespace/vendor and RAN namespace are `free5gc`, Alertmanager points to the monitoring service, and `free5gc` appears under watched namespaces and alarm references.

**Constraints:**
- You MUST stop if only `DEFAULT_NF_NAMESPACE` is correct but the watched namespace is absent because pod-health events would still ignore Free5GC.
- You MUST keep manual approval for the first dry run so no remediation executes without participant confirmation.

### 4. Verify Prometheus and Alertmanager
Check the operator resources and Free5GC scrape targets.

```bash
kubectl get pods -n monitoring
kubectl get podmonitor -n free5gc
kubectl get prometheusrule free5gc-workshop -n monitoring
kubectl exec -n anra-system deployment/anra -- \
  curl -fsS http://kube-prometheus-stack-alertmanager.monitoring.svc.cluster.local:9093/-/healthy
```

**Expected**: Monitoring pods are Ready, the Free5GC PodMonitor and workshop rules exist, and Alertmanager reports healthy.

**Constraints:**
- You MUST verify the Free5GC PodMonitor rather than counting generic Kubernetes targets.
- If Alertmanager is unhealthy or unreachable from ANRA, You MUST stop before testing the alert path.

### 5. Send a non-mutating pipeline test
Send an informational alert with no remediation SOP mapping.

```bash
python3 scripts/send-free5gc-test-alert.py
sleep 20
kubectl logs deployment/anra -n anra-system --since=2m | grep -i Free5GCWorkshopPipelineTest
```

**Expected**: ANRA receives `Free5GCWorkshopPipelineTest`; no approval or remediation execution is created.

**Constraints:**
- You MUST NOT map this test alert to an SOP because it validates detection without changing the network.
- You MUST retain the ANRA log excerpt as SOP 3 evidence.

## Examples
Use an image tag derived from the workshop-v3 commit SHA, such as `e938040-plus-v3.1`; never substitute `latest` during a recorded dry run.

## Troubleshooting
If no alert arrives, inspect Alertmanager status and confirm its receiver is `http://anra.anra-system.svc.cluster.local:8080/api/alertmanager`. If Free5GC targets are absent, verify the PodMonitor release label and Prometheus namespace selectors.
