# Remediate Free5GC Pod Repeatedly Restarting

**Duration:** ~5 minutes
**Severity:** warning (escalates to critical if the NF becomes unavailable)
**Trigger:** `free5gc_pod_restarting` — a pod in namespace `free5gc` restarted more than twice in five minutes (`increase(kube_pod_container_status_restarts_total[5m]) > 2`)

## Overview
A Free5GC pod keeps restarting. Kubernetes restarts the container each time its main process exits, with an exponential back-off (`CrashLoopBackOff`) once it fails repeatedly. The alert's `description` names the pod.

Restarts have three families of cause, and the fix differs:

| Cause | Evidence | Fix |
|---|---|---|
| Process was killed from outside (OOM, node pressure, someone ran `kill`) | `Last State: Terminated, Reason: OOMKilled` or `Error` with exit code 137/143; `--previous` logs end abruptly with no error | nothing to repair if transient; raise memory limit if OOMKilled; confirm the restart counter stops increasing |
| Configuration error | `--previous` logs show a YAML/parse error or "bind: address already in use" right after start | fix the ConfigMap, restart |
| Dependency unavailable | `--previous` logs show repeated NRF registration failures, MongoDB connection refused, or PFCP association timeouts | fix the dependency (see Related SOPs), then restart this pod |

A pod that is `Running` with a *stable* restart count is not broken — a few restarts during an earlier incident are expected. Decide from the trend, not the absolute number. Do not touch the MongoDB pod: it uses ephemeral storage and a restart loses the provisioned subscriber.

## Prerequisites
- kubectl access to the workload cluster
- Namespace `free5gc` (chart release name `free5gc`)

## Steps

### Step 1: Identify the restarting pod and its trend
```bash
kubectl get pods -n free5gc -o wide
sleep 60
kubectl get pods -n free5gc --no-headers | awk '{print $1, $3, $4}'
```
**Expected**: `RESTARTS` column identifies the pod (record as `POD`, its NF as `NF`, e.g. `smf`, and its Deployment as `DEPLOY` = `free5gc-NF-deployment`). If the count did **not** increase across the 60-second window and the pod is `Running 1/1`, the restarts have stopped: go straight to Step 5.

### Step 2: Read why the previous container exited
```bash
kubectl get pod POD -n free5gc -o jsonpath='{range .status.containerStatuses[*]}{.name}: restarts={.restartCount} last={.lastState.terminated.reason} exit={.lastState.terminated.exitCode} at {.lastState.terminated.finishedAt}{"\n"}{end}'
kubectl logs POD -n free5gc --previous --tail=40
kubectl describe pod POD -n free5gc | sed -n '/Events:/,$p'
```
**Expected**:
- `last=OOMKilled` → Step 3a.
- `last=Error exit=137` or `143` with logs ending mid-stream (no error line) → the process was killed externally. Step 3b.
- Logs end with a configuration/parse error or `address already in use` → Step 3c.
- Logs end with repeated `NRF`, `mongodb`, or `PFCP` failures → Step 3d.

### Step 3a: OOMKilled — raise the memory limit
```bash
kubectl get deploy DEPLOY -n free5gc -o jsonpath='{.spec.template.spec.containers[0].resources}{"\n"}'
kubectl patch deploy DEPLOY -n free5gc --type=json -p='[{"op":"add","path":"/spec/template/spec/containers/0/resources/limits","value":{"memory":"512Mi"}}]'
kubectl rollout status deploy DEPLOY -n free5gc --timeout=120s
```
**Expected**: new pod rolls out and stays `Running`. If no `resources` block existed the patch adds one; if a limit existed, raise it to double the previous value instead of 512Mi.

### Step 3b: Externally killed — clear the back-off and watch
The process was terminated by something other than itself (node memory pressure, a manual `kill`, a node drain). The container image and configuration are fine. Clear any accumulated back-off so Kubernetes restarts it immediately:
```bash
kubectl rollout restart deploy DEPLOY -n free5gc
kubectl rollout status deploy DEPLOY -n free5gc --timeout=120s
kubectl top node 2>/dev/null; kubectl get events -n free5gc --field-selector reason=Killing --sort-by=.lastTimestamp | tail -5
```
**Expected**: pod `Running 1/1` with `RESTARTS 0`. If node memory is above ~85% or `Killing` events recur, the real fault is at node level — escalate to `free5gc-node-not-ready.md`.

### Step 3c: Configuration error — fix the ConfigMap
```bash
kubectl get configmap free5gc-NF-config -n free5gc -o yaml | sed -n '/data:/,$p' | head -60
```
**Expected**: the ConfigMap holds the NF's `NFcfg.yaml`. Compare with the error line from Step 2 (wrong indentation, unknown key, bad IP). Edit with `kubectl edit configmap free5gc-NF-config -n free5gc`, or restore the chart's version with `helm upgrade --install free5gc /app/helm-charts/free5gc-bundle/free5gc-0.0.2.tgz -n free5gc --reuse-values`. Then `kubectl rollout restart deploy DEPLOY -n free5gc` — Free5GC NFs read config only at start.

### Step 3d: Dependency unavailable — fix upstream first
```bash
kubectl get deploy -n free5gc -o wide
kubectl logs -n free5gc deploy/free5gc-nrf-deployment --tail=20
```
**Expected**: the dependency the logs complain about (NRF, MongoDB, UPF for SMF PFCP) is itself unhealthy. Remediate it with `free5gc-nf-unavailable.md`; the restarting pod recovers on its next restart once the dependency answers. If it is still looping afterwards, `kubectl rollout restart deploy DEPLOY -n free5gc`.

### Step 4: Re-attach the UE if AMF, SMF or UPF restarted
```bash
kubectl delete pod -n free5gc -l app=packetrusher
kubectl rollout status deploy packetrusher-packetrusher -n free5gc --timeout=120s
```
**Expected**: new PacketRusher pod `Running`. The SMF holds the UE's PDU session; an SMF restart drops the session and PacketRusher does not re-establish it on its own.

### Step 5: Verify
```bash
kubectl get pods -n free5gc --no-headers | awk '{print $1, $3, $4}'
sleep 90
kubectl get pods -n free5gc --no-headers | awk '{print $1, $3, $4}'
PR=$(kubectl get pods -n free5gc -l app=packetrusher -o jsonpath='{.items[0].metadata.name}')
kubectl exec -n free5gc "$PR" -- ip vrf exec vrf0000000003 ping -c 3 8.8.8.8
```
**Expected**: all pods `Running`, the restart count for `POD` identical across the 90-second window, and the UE ping replies. The `free5gc_pod_restarting` alert resolves once the 5-minute `increase()` window rolls past the last restart — up to five minutes after the fix even when everything is healthy. Do not re-run remediation during that window.

## Rollback
```bash
kubectl rollout undo deploy DEPLOY -n free5gc      # reverts a memory-limit or image patch
kubectl rollout history deploy DEPLOY -n free5gc
```
Restarts and PacketRusher recreation have no rollback; a reverted ConfigMap edit requires another `rollout restart`.

## Troubleshooting

| Issue | Check | Fix |
|-------|-------|-----|
| Pod restarts again right after `rollout restart` | `kubectl logs POD -n free5gc --tail=20` | The cause was not external; re-run Step 2 on the fresh logs |
| `--previous` logs are empty | Container was killed before it logged, or the previous container is gone | Use `kubectl get events -n free5gc --field-selector involvedObject.name=POD`; the kubelet records the kill reason there |
| Restart count climbs on *several* NFs at once | `kubectl get nodes`, `kubectl top node` | Node-level problem (memory, disk pressure, kubelet) — `free5gc-node-not-ready.md` |
| UE ping fails though all pods are stable | AMF log shows no registration | Run Step 4 |

## Related SOPs
- **Escalation:** `sops/day2-remediate/core/free5gc-nf-unavailable.md` (pod never becomes ready), `sops/day2-remediate/infra/free5gc-node-not-ready.md`
- **Follow-on:** `sops/day2-remediate/core/free5gc-registration-unavailable.md`
- **Prevention:** `sops/day1-deploy/validate-free5gc-e2e.sop.md`
