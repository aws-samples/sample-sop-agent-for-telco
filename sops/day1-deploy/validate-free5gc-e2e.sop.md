# Validate Free5GC End to End

## Overview
Validate the PacketRusher registration, PDU session, DNS, user-plane connectivity, and throughput after the workshop-v3 Free5GC deployment.

## Parameters

- **namespace** (optional, default: `free5gc`): Namespace containing Free5GC and PacketRusher.

**Constraints for parameter acquisition:**
- If all required parameters are already provided, You MUST proceed to the Steps
- If any required parameters are missing, You MUST ask for them before proceeding
- When asking for parameters, You MUST request all parameters in a single prompt
- When asking for parameters, You MUST use the exact parameter names as defined

## Prerequisites
- The Free5GC deployment SOP completed successfully.
- `kubectl` points to the CloudFormation-provisioned workshop-v3 cluster.

## Steps

### 1. Run the functional test suite
Execute the deterministic test script inherited from the validated IND321 flow.

```bash
export NAMESPACE="${NAMESPACE:-free5gc}"
bash tests/free5gc/run-tests.sh | tee /tmp/workshop-v3-free5gc-e2e.log
grep -q 'ALL TESTS PASSED' /tmp/workshop-v3-free5gc-e2e.log
```

**Expected**: The test suite reports `ALL TESTS PASSED`, including UE IP assignment, user-plane ping, DNS, and throughput.

**Constraints:**
- You MUST preserve the complete test log as evidence.
- You MUST NOT infer success from pod health alone because a Running core can still have a broken PDU session or user plane.
- If the script reports any failure, You MUST stop before deploying SOP 3.

### 2. Capture control-plane evidence
Collect the AMF, SMF, UPF, and PacketRusher evidence needed to establish the healthy baseline.

```bash
kubectl logs -n "${NAMESPACE:-free5gc}" deployment/free5gc-amf-deployment --tail=100 | grep -iE 'registration|registered|NG'
kubectl logs -n "${NAMESPACE:-free5gc}" deployment/free5gc-smf-deployment --tail=100 | grep -iE 'PFCP|session'
kubectl logs -n "${NAMESPACE:-free5gc}" deployment/free5gc-upf-deployment --tail=100 | grep -iE 'PFCP|association'
kubectl logs -n "${NAMESPACE:-free5gc}" -l app=packetrusher --tail=100 | grep -iE 'PDU|address received|val0000'
```

**Expected**: Logs show successful NG registration, PFCP association, PDU-session establishment, and a UE interface/address.

**Constraints:**
- You MUST record these outputs before introducing monitoring or faults so later recovery can be compared with the same baseline.
- You SHOULD redact identifiers if the workshop values are changed from disposable test identities.

## Examples
Run with the default `free5gc` namespace immediately after `deploy-free5gc-core.sop.md`.

## Troubleshooting
A missing UE interface usually indicates subscriber slice inconsistency; inspect the subscriber record and SMF logs. A working PDU session with failed internet ping indicates N6 routing, NAT, or source/destination-check configuration.
