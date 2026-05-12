# Remediate UPF PFCP Association Loss

**Severity:** Critical
**Duration:** ~5 minutes

## Overview
The PFCP association between SMF and UPF has broken. No new PDU sessions can be established.

## Steps

### Step 1: Check UPF pod status
```tool: kubectl
kubectl get pods -l app.kubernetes.io/name=upf -n open5gs
```
**Expected**: UPF pod Running. If CrashLoopBackOff → Step 2.

### Step 2: If UPF crashed, wait for restart
```tool: kubectl
kubectl wait --for=condition=ready pod -l app.kubernetes.io/name=upf -n open5gs --timeout=120s
```
**Expected**: `condition met`

### Step 3: Check SMF logs for PFCP status
```tool: kubectl
kubectl logs -l app.kubernetes.io/name=smf -n open5gs --tail=10 | grep -i pfcp
```
**Expected**: `PFCP associated`. If no PFCP message → Step 4.

### Step 4: Restart SMF to re-establish PFCP
```tool: kubectl
kubectl delete pod -l app.kubernetes.io/name=smf -n open5gs
```
**Expected**: SMF pod deleted, new one starts

### Step 5: Wait for SMF and verify PFCP
```tool: kubectl
sleep 15 && kubectl wait --for=condition=ready pod -l app.kubernetes.io/name=smf -n open5gs --timeout=120s && kubectl logs -l app.kubernetes.io/name=smf -n open5gs --tail=10 | grep -i pfcp
```
**Expected**: `PFCP associated` message

### Step 6: Verify UE can establish PDU session
```tool: kubectl
kubectl rollout restart deployment/ueransim-ueransim-gnb-ues -n srsran && sleep 20 && kubectl logs deploy/ueransim-ueransim-gnb-ues -n srsran --tail=5
```
**Expected**: `PDU Session establishment is successful`
