# Reset 5G Core Cluster

**Duration:** ~5 minutes
**Severity:** N/A (operator-initiated)
**Target:** EKS cluster

## Overview

Tears down the 5G core deployment and redeploys it cleanly. Use when:
- A SOP failed mid-execution leaving inconsistent state
- AUSF subscriber state corrupted by re-running validate-e2e
- Pods stuck in Pending/Error and ordinary remediation isn't working
- You want to start over without rebuilding the entire workshop environment

## Constraints

- You MUST NOT delete the EKS cluster itself, only the workloads on it
- You MUST preserve the ANRA agent and monitoring stack
- You MUST verify the reset completed before declaring success

## Steps

### Step 1: Capture diagnostic snapshot

```tool: shell
mkdir -p /tmp/reset-$(date +%s)
DIAG=$(ls -dt /tmp/reset-* | head -1)
kubectl get pods -A > $DIAG/pods-before.txt
kubectl get events -A --sort-by='.lastTimestamp' > $DIAG/events-before.txt
echo "Diagnostic saved to $DIAG"
```
**Expected**: directory created with two files

### Step 2: Uninstall Open5GS Helm release

```tool: shell
helm uninstall open5gs -n open5gs --wait --timeout=60s 2>&1 || true
```
**Expected**: `release "open5gs" uninstalled` OR `release: not found`

### Step 3: Delete the open5gs namespace (cleans PVCs, secrets, configmaps)

```tool: shell
kubectl delete namespace open5gs --wait --timeout=120s 2>&1 || true
```
**Expected**: `namespace "open5gs" deleted` OR `namespaces "open5gs" not found`

### Step 4: Uninstall UERANSIM Helm release (if deployed)

```tool: shell
helm uninstall ueransim -n srsran --wait --timeout=60s 2>&1 || true
```
**Expected**: success or "not found"

### Step 5: Verify clean state

```tool: kubectl
get pods -n open5gs 2>&1 || echo "namespace gone (good)"
```
**Expected**: `No resources found` OR `Error from server (NotFound): namespaces "open5gs" not found`

### Step 6: Reapply ArgoCD app to redeploy from Git

```tool: shell
kubectl get application -n argocd open5gs -o name && \
  argocd app sync open5gs --prune 2>&1 || \
  echo "ArgoCD not in use; redeploy manually with deploy-5g-core.md"
```
**Expected**: `Application synced`

### Step 7: Wait for NFs to become Ready

```tool: shell
sleep 30 && kubectl wait --for=condition=ready pod \
  -l app.kubernetes.io/part-of=open5gs \
  -n open5gs --timeout=180s
```
**Expected**: All pods `condition met`

### Step 8: Verify NF health

```tool: kubectl
get pods -n open5gs --no-headers | wc -l
```
**Expected**: Number ≥ 8 (matches NF count for the deployed Open5GS chart)

## Success Criteria

- All Open5GS NFs are Running and Ready
- No pods in CrashLoopBackOff or Error state
- ANRA dashboard shows the cluster as healthy

## Rollback

There is no rollback for this SOP — it IS the rollback.

## Troubleshooting

| Symptom | Action |
|---------|--------|
| Step 3 hangs >120s | Pods have finalizers; run `kubectl get pods -n open5gs -o name \| xargs -I {} kubectl patch {} -n open5gs --type json -p '[{"op":"remove","path":"/metadata/finalizers"}]'` |
| Step 6 fails with "Application not found" | ArgoCD not deployed in this workshop variant; manually redeploy with `helm install open5gs <chart>` per `deploy-5g-core.md` |
| Step 7 times out | Some pods are still scheduling; rerun `kubectl get pods -n open5gs` to see status, then wait another 60s |

## Manual Test Plan

```bash
# 1. Deploy workshop normally (deploy-5g-core.md)
# 2. Break it: kubectl delete pod amf-0 -n open5gs (or scale to 0)
# 3. Run reset-cluster.md
# 4. Verify all NFs are healthy
```
