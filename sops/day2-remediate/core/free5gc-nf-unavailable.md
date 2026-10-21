# Remediate Free5GC Network Function Unavailable

**Duration:** ~5 minutes
**Severity:** critical
**Trigger:** `free5gc_nf_unavailable` — a `free5gc-*` Deployment in namespace `free5gc` reports unavailable replicas (`kube_deployment_status_replicas_unavailable > 0`)

## Overview
A Free5GC core network function (AMF, SMF, UPF, NRF, AUSF, UDM, UDR, PCF or NSSF) has no ready replica. The impact depends on the NF: AMF or UPF down means the PacketRusher UE loses registration or user-plane traffic within seconds; NRF down stops NFs discovering each other; UDM/UDR/AUSF down blocks new registrations but leaves existing sessions up.

The alert's `description` names the Deployment (`free5gc-<nf>-deployment`). Diagnose *why* it has no replica before acting: the three common causes have different fixes.

| Cause | Symptom | Fix |
|---|---|---|
| Desired replicas set to 0 (operator action, scale-down, or scripted drain) | `READY 0/0`, no pods, no events | scale back to 1 |
| Pod cannot start (bad image, missing ConfigMap, scheduling) | `READY 0/1`, pod `ImagePullBackOff` / `Pending` / `CreateContainerConfigError` | fix the referenced object, then restart |
| Pod crashes after start (config error, dependency down) | `READY 0/1`, pod `CrashLoopBackOff` / `Error` | follow `free5gc-pod-crashloop.md` |

Do not restart or delete anything until Step 2 has identified the cause. Deleting the MongoDB pod would lose the provisioned subscriber — MongoDB is out of scope for this SOP.

## Prerequisites
- kubectl access to the workload cluster
- Namespace `free5gc` (chart release name `free5gc`)

## Steps

### Step 1: Identify the affected Deployment
```bash
kubectl get deploy -n free5gc -o wide
```
**Expected**: all `free5gc-*-deployment` rows show `READY 1/1`. The unhealthy one shows `0/0` (desired replicas is zero) or `0/1` (a pod exists but is not ready). Record its name as `DEPLOY` (for example `free5gc-amf-deployment`) and its NF short name as `NF` (`amf`).

### Step 2: Determine why it is unavailable
```bash
kubectl get deploy DEPLOY -n free5gc -o jsonpath='desired={.spec.replicas} ready={.status.readyReplicas} unavailable={.status.unavailableReplicas}{"\n"}'
kubectl get pods -n free5gc -l epc-mode=NF -o wide
kubectl get events -n free5gc --sort-by=.lastTimestamp --field-selector type=Warning | tail -20
```
**Expected**:
- `desired=0` → cause is scale-to-zero. Go to Step 3a.
- `desired=1` and a pod in `ImagePullBackOff`, `Pending` or `CreateContainerConfigError` → Step 3b.
- `desired=1` and a pod in `CrashLoopBackOff` or `Error` → stop here and run `sops/day2-remediate/core/free5gc-pod-crashloop.md` instead.

### Step 3a: Restore the replica count
```bash
kubectl scale deploy DEPLOY -n free5gc --replicas=1
kubectl rollout status deploy DEPLOY -n free5gc --timeout=120s
```
**Expected**: `deployment "DEPLOY" successfully rolled out`. Free5GC NFs register with the NRF on start; no further action is needed for the NF itself.

### Step 3b: Fix a pod that cannot start
```bash
kubectl describe pod -n free5gc -l epc-mode=NF | sed -n '/Events:/,$p'
kubectl get configmap free5gc-NF-config -n free5gc
```
**Expected**: the Events block names the missing object or the image that cannot be pulled. Compare the image against the healthy NFs (`kubectl get deploy -n free5gc -o jsonpath='{range .items[*]}{.metadata.name}{" "}{.spec.template.spec.containers[0].image}{"\n"}{end}'`); if the failing Deployment has a different tag, patch it back to the common tag. If a ConfigMap is missing, re-run `helm upgrade --install free5gc /app/helm-charts/free5gc-bundle/free5gc-0.0.2.tgz -n free5gc --reuse-values` to recreate it. Then:
```bash
kubectl rollout restart deploy DEPLOY -n free5gc
kubectl rollout status deploy DEPLOY -n free5gc --timeout=120s
```

### Step 4: Re-attach the UE if the AMF or UPF was affected
PacketRusher does not reconnect automatically after the AMF or UPF restarts: it holds a singleton Multus IP and must be recreated to re-register.
```bash
kubectl delete pod -n free5gc -l app=packetrusher
kubectl rollout status deploy packetrusher-packetrusher -n free5gc --timeout=120s
```
**Expected**: a new PacketRusher pod is `Running`. Skip this step if the affected NF was NRF, AUSF, UDM, UDR, PCF or NSSF and the UE is still registered (Step 5 shows `Registered: 1`).

### Step 5: Verify
```bash
kubectl get deploy -n free5gc -o wide
kubectl logs -n free5gc deploy/free5gc-amf-deployment --tail=50 | grep -iE 'registration|NG Setup|gNB' | tail -5
PR=$(kubectl get pods -n free5gc -l app=packetrusher -o jsonpath='{.items[0].metadata.name}')
kubectl exec -n free5gc "$PR" -- ip vrf exec vrf0000000003 ping -c 3 8.8.8.8
```
**Expected**: every `free5gc-*-deployment` is `READY 1/1`; AMF log shows a successful gNB NG Setup and UE registration; the ping through the UE VRF receives replies. The `free5gc_nf_unavailable` alert resolves on the next Prometheus evaluation (within about a minute) and `free5gc_registration_unavailable`, if it fired, resolves once the UE is back.

## Rollback
Steps 3a, 3b and 4 only restore desired state and restart pods; there is nothing to undo. If an image or ConfigMap patch in Step 3b made things worse, `kubectl rollout undo deploy DEPLOY -n free5gc` returns to the previous revision.

## Troubleshooting

| Issue | Check | Fix |
|-------|-------|-----|
| Scale to 1 succeeds but pod stays `Pending` | `kubectl describe pod -n free5gc -l epc-mode=NF` shows `FailedScheduling` or a Multus/NAD error | Only one Multus static IP exists per NF; make sure no stale pod for the same NF is still `Terminating` (`kubectl get pods -n free5gc -l epc-mode=NF`), then wait for it to disappear or force-delete it (`--grace-period=0 --force`) |
| NF is `Running` but AMF shows no gNB | PacketRusher pod age predates the AMF restart | Run Step 4 |
| UE pings fail after everything is `Running` | `kubectl logs -n free5gc deploy/free5gc-upf-deployment --tail=30` for gtp5g or N3/N6 errors | Recreate PacketRusher (Step 4); if the UPF itself logs gtp5g errors, escalate — the kernel module is node-level |
| Alert does not clear | `kubectl get deploy -n free5gc` still shows `0/1` | The Deployment is unhealthy for a second reason; repeat Step 2 |

## Related SOPs
- **Escalation:** `sops/day2-remediate/core/free5gc-pod-crashloop.md` (pod starts but crashes), `sops/day2-remediate/infra/free5gc-node-not-ready.md` (the node hosting the NF is NotReady — fix the node first)
- **Follow-on:** `sops/day2-remediate/core/free5gc-registration-unavailable.md` if the UE does not re-register after the NF is healthy
- **Prevention:** `sops/day1-deploy/validate-free5gc-e2e.sop.md` to re-baseline the stack
