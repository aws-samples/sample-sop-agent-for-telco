# Remediate Free5GC UE Registration Unavailable

**Duration:** ~5 minutes
**Severity:** critical
**Trigger:** `free5gc_registration_unavailable` — the AMF reports no registered UE (`sum(free5gc_amf_business_ue_gmm_state_count{gmm_state="Registered"}) < 1`)

## Overview
No UE is registered on the Free5GC AMF. In this environment there is exactly one simulated UE, provided by the PacketRusher pod (one gNB + one UE, MSIN `0000000003`, PLMN 208/93, TAC `000001`, DNN `internet`). Registration is lost when:

| Cause | Where it shows | Fix |
|---|---|---|
| PacketRusher pod is gone or restarted (scaled down, evicted, deleted) | no `app=packetrusher` pod, or a young pod with no registration in its log | restore the pod; recreate it so it re-registers |
| AMF / SMF / UPF restarted and PacketRusher did not reconnect | core pods are young, PacketRusher is old and idle | recreate PacketRusher |
| gNB ↔ AMF mismatch (PLMN, TAC, slice SST/SD) after a config change | AMF log: `NG Setup failure`, `PLMN not allowed`, `Registration reject` | align PacketRusher ConfigMap with the AMF, recreate PacketRusher |
| Subscriber missing in the UDR/MongoDB | AMF/AUSF log: authentication failure, `SUPI not found` | re-run subscriber provisioning (do **not** delete MongoDB) |
| N2 connectivity (Multus ENI, static IP) | PacketRusher log: SCTP connect timeout to the AMF N2 address | check Multus NADs and the AMF N2 IP |

Check the core first: if `free5gc_nf_unavailable` is also firing, remediate it with `free5gc-nf-unavailable.md` before this SOP — the UE cannot register against an AMF that is not running.

## Prerequisites
- kubectl access to the workload cluster
- Namespace `free5gc`; chart releases `free5gc` (core) and `packetrusher` (gNB/UE simulator)
- `free5gc_nf_unavailable` is not firing (or has been remediated)

## Steps

### Step 1: Confirm the core is up and locate the simulator
```bash
kubectl get deploy -n free5gc -o wide
kubectl get pods -n free5gc -l app=packetrusher -o wide
```
**Expected**: all `free5gc-*-deployment` are `READY 1/1`. The PacketRusher row shows whether the pod exists (`packetrusher-packetrusher` Deployment, `0/0` means it was scaled down) and its age relative to the AMF/SMF/UPF pods.

### Step 2: Read both sides of the registration
```bash
kubectl logs -n free5gc deploy/free5gc-amf-deployment --tail=60 | grep -iE 'NG Setup|gNB|Registration|PLMN|reject|SUPI' | tail -15
PR=$(kubectl get pods -n free5gc -l app=packetrusher -o jsonpath='{.items[0].metadata.name}' 2>/dev/null)
[ -n "$PR" ] && kubectl logs -n free5gc "$PR" --tail=60 | grep -iE 'NGAP|SCTP|Registration|PDU|reject|timeout|error' | tail -15
```
**Expected**: on a healthy system the AMF shows `NG Setup procedure is successful` followed by `Registration accept`, and PacketRusher shows `Registration accept` and `PDU Session Establishment Accept`. Map what you see to the cause table:
- no PacketRusher pod, or its log stops at startup → Step 3a
- PacketRusher log shows a successful registration *older* than the AMF/SMF/UPF pod age, nothing since → Step 3a
- `NG Setup failure`, `PLMN … not allowed`, `Registration reject` with a cause code → Step 3b
- `authentication failure`, `SUPI not found`, AUSF/UDM errors → Step 3c
- `SCTP` connect/timeout errors in PacketRusher → Step 3d

### Step 3a: Restore and re-register the simulated UE
PacketRusher owns a singleton Multus IP on N2/N3 and only registers at process start, so it must be recreated rather than restarted in place.
```bash
kubectl scale deploy packetrusher-packetrusher -n free5gc --replicas=1
kubectl delete pod -n free5gc -l app=packetrusher --ignore-not-found
kubectl rollout status deploy packetrusher-packetrusher -n free5gc --timeout=120s
```
**Expected**: a new PacketRusher pod `Running 1/1`. Go to Step 4.

### Step 3b: Align gNB and AMF identities
```bash
kubectl get configmap free5gc-amf-config -n free5gc -o yaml | grep -nE 'mcc|mnc|tac|sst|sd:' | head -12
kubectl get configmap packetrusher-packetrusher -n free5gc -o yaml | grep -nE 'mcc|mnc|tac|sst|sd:|gnbid' | head -12
```
**Expected**: both sides agree on MCC `208`, MNC `93`, TAC `000001`, SST `01`, SD `112233`. The workshop baseline is the **AMF** configuration; correct the PacketRusher ConfigMap to match it (`kubectl edit configmap packetrusher-packetrusher -n free5gc`), or restore the chart defaults with `helm upgrade --install packetrusher /app/helm-charts/free5gc-bundle/packetrusher-0.0.3.tgz -n free5gc --reuse-values`. Do not edit the AMF to match a drifted gNB — every other NF shares the AMF's PLMN. Then run Step 3a to recreate PacketRusher.

### Step 3c: Restore the subscriber
```bash
kubectl get pods -n free5gc -l app=mongodb
kubectl logs -n free5gc deploy/free5gc-udr-deployment --tail=30 | grep -iE 'mongo|error|not found' | tail -5
kubectl get job subprov -n free5gc -o wide
```
**Expected**: MongoDB `Running`; the UDR can reach it. The `subprov` Job seeds subscribers through the Free5GC WebUI once at install time. If the MongoDB pod is younger than the Job, the subscriber was lost with the pod's ephemeral storage. Re-run provisioning by deleting the completed Job and letting Helm recreate it:
```bash
kubectl delete job subprov -n free5gc --ignore-not-found
helm upgrade --install free5gc /app/helm-charts/free5gc-bundle/free5gc-0.0.2.tgz -n free5gc --reuse-values
kubectl wait --for=condition=complete job/subprov -n free5gc --timeout=180s
```
Then Step 3a. **Never** delete the MongoDB pod or Deployment as part of this SOP.

### Step 3d: Check the N2 path
```bash
kubectl get network-attachment-definitions -n free5gc
kubectl get pod -n free5gc -l epc-mode=amf -o jsonpath='{.items[0].metadata.annotations.k8s\.v1\.cni\.cncf\.io/network-status}' | tr ',' '\n' | grep -E 'name|ips' | head -8
kubectl get configmap packetrusher-packetrusher -n free5gc -o yaml | grep -nE 'amf|ipAddress' | head -6
```
**Expected**: the AMF's N2 interface IP equals the `amf.ipAddress` PacketRusher is configured to dial (default `10.100.4.36`). If they differ, the AMF pod was rescheduled with a different Multus address: recreate the AMF so it takes its static IP (`kubectl rollout restart deploy free5gc-amf-deployment -n free5gc`), then Step 3a. If the NADs are missing, escalate — the N2/N3 Multus definitions are created at deploy time (`sops/day1-deploy/deploy-free5gc-core.sop.md`).

### Step 4: Verify registration and the user plane
```bash
sleep 20
kubectl logs -n free5gc deploy/free5gc-amf-deployment --tail=30 | grep -iE 'NG Setup|Registration accept' | tail -3
PR=$(kubectl get pods -n free5gc -l app=packetrusher -o jsonpath='{.items[0].metadata.name}')
kubectl logs -n free5gc "$PR" --tail=40 | grep -iE 'Registration|PDU Session' | tail -4
kubectl exec -n free5gc "$PR" -- ip vrf exec vrf0000000003 ip address show val0000000003
kubectl exec -n free5gc "$PR" -- ip vrf exec vrf0000000003 ping -c 3 8.8.8.8
```
**Expected**: AMF logs `NG Setup procedure is successful` and `Registration accept`; PacketRusher logs `PDU Session Establishment Accept`; interface `val0000000003` has a `10.63.x.x` address; the ping replies. The `free5gc_registration_unavailable` alert resolves on the next AMF metric scrape (within about a minute).

## Rollback
Step 3a is a pod recreation with no rollback. For Step 3b/3c, `helm upgrade --reuse-values` restores chart defaults; `kubectl rollout undo deploy packetrusher-packetrusher -n free5gc` reverts a manual ConfigMap-driven rollout. Changes to the AMF are out of scope for this SOP.

## Troubleshooting

| Issue | Check | Fix |
|-------|-------|-----|
| New PacketRusher pod stuck `ContainerCreating` | `kubectl describe pod -n free5gc -l app=packetrusher` shows a Multus IP conflict | The old pod still holds the static N2/N3 IP; wait for it to terminate or `kubectl delete pod … --grace-period=0 --force`, then let the Deployment recreate it |
| AMF accepts registration, but no PDU session | SMF / UPF logs: `PFCP` association errors | UPF or SMF is unhealthy — `free5gc-nf-unavailable.md` or `free5gc-pod-crashloop.md`, then recreate PacketRusher |
| Registration accepted but `val0000000003` has no address | PacketRusher log for `PDU Session Establishment Reject`, SMF log for DNN/slice errors | DNN (`internet`) or slice (SST 01 / SD 112233) mismatch between PacketRusher and the SMF ConfigMap — align PacketRusher, recreate |
| Ping fails although the UE has an address | `kubectl logs -n free5gc deploy/free5gc-upf-deployment --tail=30` | UPF gtp5g / N6 issue; node-level, escalate |
| Metric still `< 1` after a visible `Registration accept` | `kubectl get podmonitor -n free5gc` | AMF metrics are not being scraped (`free5gc_metrics_missing`); registration is fine, the alert is a monitoring gap |

## Related SOPs
- **Prerequisite:** `sops/day2-remediate/core/free5gc-nf-unavailable.md` when the AMF/SMF/UPF is down
- **Escalation:** `sops/day2-remediate/core/free5gc-pod-crashloop.md` (SMF/UPF looping), `sops/day2-remediate/infra/free5gc-node-not-ready.md`
- **Prevention / re-baseline:** `sops/day1-deploy/validate-free5gc-e2e.sop.md`
