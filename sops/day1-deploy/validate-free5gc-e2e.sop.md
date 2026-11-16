# Validate Free5GC End to End

## Overview
Validate the PacketRusher registration, PDU session, DNS, and user-plane connectivity after the workshop-v3 Free5GC deployment. Throughput testing is optional and runs only when `IPERF_IMAGE` is set to an immutable iperf3 image.

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

**Expected**: The test suite reports `ALL TESTS PASSED`, covering UE IP assignment, user-plane ping, and DNS. The throughput section reports `[SKIP]` unless `IPERF_IMAGE` is set.

**Constraints:**
- You MUST preserve the complete test log as evidence.
- You MUST NOT infer success from pod health alone because a Running core can still have a broken PDU session or user plane.
- You MUST treat a `[SKIP]` throughput line as expected when `IPERF_IMAGE` is unset; it MUST NOT be reported as a failure or a gap.
- You MUST judge the run by the `FAIL:` count in the `PASS: N   FAIL: N   SKIP: N` summary and the `ALL TESTS PASSED` line, not by the presence of `[SKIP]`.
- If the script reports any `[FAIL]` line or a non-zero `FAIL:` count, You MUST stop before deploying SOP 3.

### 2. Capture control-plane evidence
Collect the AMF, SMF, UPF, and PacketRusher evidence needed to establish the healthy baseline.

```bash
kubectl logs -n "${NAMESPACE:-free5gc}" deployment/free5gc-amf-deployment --tail=100 | grep -iE 'registration|registered|NG'
kubectl logs -n "${NAMESPACE:-free5gc}" deployment/free5gc-smf-deployment --tail=100 | grep -iE 'PFCP|session'
kubectl logs -n "${NAMESPACE:-free5gc}" deployment/free5gc-upf-deployment --tail=100 | grep -iE 'PFCP|association|heartbeat|session'
kubectl logs -n "${NAMESPACE:-free5gc}" -l app=packetrusher --tail=100 | grep -iE 'PDU|address received|val0000'
```

**Expected**: Logs show successful NG registration, an established N4 (PFCP) link, PDU-session establishment, and a UE interface/address. The UPF log shows either a PFCP association message or ongoing PFCP heartbeat/session activity.

**Constraints:**
- You MUST record these outputs before introducing monitoring or faults so later recovery can be compared with the same baseline.
- You MUST treat the N4 link as PASS when the UPF log shows either a PFCP association message or ongoing PFCP heartbeat/session activity, because heartbeats are only exchanged on an established association.
- You MUST NOT report the N4 link as failed solely because the association message has rotated out of the `--tail` window.
- You SHOULD redact identifiers if the workshop values are changed from disposable test identities.

## Examples
Run with the default `free5gc` namespace immediately after `deploy-free5gc-core.sop.md`.

## Troubleshooting
A missing UE interface usually indicates subscriber slice inconsistency; inspect the subscriber record and SMF logs. A working PDU session with failed internet ping indicates N6 routing, NAT, or source/destination-check configuration.
