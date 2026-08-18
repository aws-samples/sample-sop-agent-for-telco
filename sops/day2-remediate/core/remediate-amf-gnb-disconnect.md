# Remediate AMF-gNB Disconnection

**Duration:** ~5 minutes
**Severity:** critical
**Trigger:** `core_amf_gnb_down` — AMF reports 0 connected gNBs

## Overview
The gNB has lost its SCTP/N2 connection to the AMF. All UEs on the affected cell lose service. This SOP diagnoses the network path and restores connectivity.

## Prerequisites
- kubectl access to cluster
- SSM access to edge worker nodes

## Steps

### Step 1: Confirm gNB is disconnected from AMF
```bash
kubectl logs -l app.kubernetes.io/name=amf -n open5gs --tail=20 | grep -i "removed\|Number of gNBs"
```
**Expected**: `Number of gNBs is now 0` or `Removed` messages

### Step 2: Check UERANSIM gNB pod status
```bash
kubectl get pod ueransim-gnb -n srsran -o wide
```
**Expected**: Pod should be Running. If not, that's the root cause.

### Step 3: Check UERANSIM gNB logs for connection errors
```bash
kubectl logs ueransim-gnb -n srsran --tail=20 | grep -iE "error|fail|timeout|refused"
```
**Expected**: Connection errors indicate network path issue

### Step 4: Verify AMF service is reachable from gNB network
```bash
kubectl get svc -n open5gs | grep amf
```
**Expected**: AMF NGAP service on port 38412

### Step 5: Test SCTP connectivity from gNB pod to AMF
```bash
kubectl exec ueransim-gnb -n srsran -- nc -z -w5 open5gs-amf-ngap.open5gs.svc.cluster.local 38412
```
**Expected**: Connection successful. If timeout → network partition.

### Step 6: If network path is broken, check VPN tunnel (for hybrid setups)
```bash
kubectl get nodes -o wide | grep -E "mi-|192.168"
```
**Expected**: Edge nodes showing Ready. If NotReady → VPN/transport issue.

### Step 7: Restart UERANSIM gNB to re-establish connection

> **Note:** UERANSIM gNB should be a Deployment, not a bare Pod. If it's a bare Pod, `kubectl delete` will remove it permanently. Convert to Deployment first if needed.

```bash
kubectl rollout restart deployment ueransim-gnb -n srsran
```
**Expected**: New pod starts, connects to AMF

If the pod doesn't exist (bare Pod was deleted), recreate it:
```bash
kubectl apply -f - <<EOF
apiVersion: apps/v1
kind: Deployment
metadata:
  name: ueransim-gnb
  namespace: srsran
spec:
  replicas: 1
  selector:
    matchLabels:
      app: ueransim-gnb
  template:
    metadata:
      labels:
        app: ueransim-gnb
    spec:
      nodeSelector:
        role: region
      containers:
      - name: gnb
        image: openverso/ueransim:3.2.6
        command: ["nr-gnb"]
        args: ["-c", "/config/gnb.yaml"]
        volumeMounts:
        - name: config
          mountPath: /config
      volumes:
      - name: config
        configMap:
          name: ueransim-config
EOF
```
**Expected**: Deployment created, pod starts

### Step 8: Wait and verify reconnection
```bash
sleep 15
kubectl logs -l app=ueransim-gnb -n srsran --tail=5 | grep "NG Setup"
```
**Expected**: `NG Setup procedure is successful`

## Verification

### Final Check
```bash
kubectl logs -l app.kubernetes.io/name=amf -n open5gs --tail=5 | grep "Number of gNBs"
```
**Expected**: `Number of gNBs is now 1`

## Rollback
If gNB cannot reconnect after restart, check AMF pod health:
```bash
kubectl delete pods -l app.kubernetes.io/name=amf -n open5gs
```

## Troubleshooting

| Issue | Check | Fix |
|-------|-------|-----|
| gNB pod not running | `kubectl get pod ueransim-gnb -n srsran` | Recreate pod from manifest |
| SCTP timeout | `nc -z` to AMF port 38412 | Check network policies, VPN tunnel |
| AMF rejecting gNB | AMF logs for reject reason | Verify PLMN/TAC match between gNB and AMF config |
| Edge node NotReady | `kubectl get nodes` | Check VPN, restart kubelet on edge |

## Related SOPs
- **Root cause:** `day2-remediate/infra/remediate-network-partition.md`
- **Downstream:** UE deregistration follows gNB disconnect
