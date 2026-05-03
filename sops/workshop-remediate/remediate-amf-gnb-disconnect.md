# Remediate AMF-gNB Disconnect

**Severity:** Critical
**Duration:** ~5 minutes

## Overview
The gNB has lost its SCTP connection to the AMF. All UEs served by this gNB lose service.

## Steps

### Step 1: Check gNB logs
```tool: kubectl
kubectl logs deploy/ueransim-ueransim-gnb -n srsran --tail=15
```
**Expected**: Look for `SCTP connection established` or error messages

### Step 2: Check AMF pod status
```tool: kubectl
kubectl get pods -l app.kubernetes.io/name=amf -n open5gs
```
**Expected**: AMF pod Running. If not → wait for restart.

### Step 3: Get current AMF pod IP
```tool: kubectl
AMF_POD_IP=$(kubectl get pod -n open5gs -l app.kubernetes.io/name=amf -o jsonpath='{.items[0].status.podIP}') && echo "AMF Pod IP: $AMF_POD_IP"
```
**Expected**: Pod IP address

### Step 4: Check if gNB is pointing to correct AMF IP
```tool: kubectl
kubectl exec deploy/ueransim-ueransim-gnb -n srsran -- cat /etc/ueransim/gnb.yaml | grep -A2 amfConfigs
```
**Expected**: Address should match AMF pod IP from Step 3

### Step 5: If AMF IP changed, update UERANSIM
```tool: shell
helm upgrade ueransim oci://registry-1.docker.io/gradiant/ueransim-gnb --version 0.2.6 --namespace srsran --reuse-values --set amf.ip=$AMF_POD_IP
```
**Expected**: `Release "ueransim" has been upgraded`

### Step 6: Verify gNB reconnects
```tool: kubectl
sleep 15 && kubectl logs deploy/ueransim-ueransim-gnb -n srsran --tail=10
```
**Expected**: `NG Setup procedure is successful`

### Step 7: Verify UE re-registers
```tool: kubectl
kubectl rollout restart deployment/ueransim-ueransim-gnb-ues -n srsran && sleep 20 && kubectl logs deploy/ueransim-ueransim-gnb-ues -n srsran --tail=5
```
**Expected**: `Initial Registration is successful`
