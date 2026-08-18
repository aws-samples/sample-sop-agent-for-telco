# Deploy 5G Core Network (Open5GS)

**Duration:** ~10 minutes
**Target:** EKS cluster (region nodes)

## Overview
Deploy Open5GS 5G SA core network with all control plane NFs (AMF, SMF, NRF, SCP, AUSF, UDM, UDR, PCF, NSSF, BSF) and MongoDB subscriber database. UPF is deployed separately on edge nodes.

## Prerequisites
- kubectl access to EKS cluster
- Helm 3 installed
- Nodes labeled `role=region` for control plane NFs

## Steps

### Step 1: Add Gradiant Helm repo
```bash
helm repo add gradiant https://gradiant.github.io/5g-charts/ && helm repo update
```
**Expected**: `"gradiant" has been added`

### Step 2: Deploy Open5GS
```bash
helm install open5gs gradiant/open5gs -n open5gs --create-namespace \
  --set global.image.tag=2.7.7 \
  --set mongodb.enabled=true \
  --set upf.enabled=false \
  --set pcrf.enabled=false \
  --set mme.enabled=false \
  --set sgwc.enabled=false \
  --set sgwu.enabled=false \
  --set hss.enabled=false
```
**Expected**: `STATUS: deployed`

> **Note:** The Gradiant chart deploys both 4G EPC and 5G SA NFs by default. Disable 4G components (PCRF, MME, SGWC, SGWU, HSS) — they are not needed for 5G SA and PCRF will crashloop because it requires a Diameter connection that isn't configured.

> **Note:** If the bitnami MongoDB image is unavailable (registry issues), the chart may fail. Override with: `--set mongodb.image.repository=mongo --set mongodb.image.tag=7.0`

### Step 3: Wait for all pods to be ready
```bash
kubectl wait --for=condition=ready pod --all -n open5gs --timeout=180s
```
**Expected**: All pods report `condition met`

### Step 4: Verify NRF has registered all NFs
```bash
kubectl logs -l app.kubernetes.io/name=nrf -n open5gs --tail=20 | grep -i "registered"
```
**Expected**: Multiple NF registration messages (AMF, SMF, AUSF, UDM, UDR, PCF, NSSF, BSF)

### Step 5: Verify AMF is listening for gNB connections
```bash
kubectl logs -l app.kubernetes.io/name=amf -n open5gs --tail=10 | grep -i "ngap"
```
**Expected**: NGAP server started on port 38412

## Verification

### Final Check
```bash
kubectl get pods -n open5gs --no-headers | awk '{print $1, $3}' | column -t
```
**Expected**: All pods in `Running` state. If PCRF shows `Error`/`CrashLoopBackOff`, scale it down: `kubectl scale deployment open5gs-pcrf -n open5gs --replicas=0`

## Known Issues

### SBI mesh breaks after NF restarts
If you restart individual NFs (e.g., during troubleshooting), the SCP caches stale NF endpoints and inter-NF communication breaks. Symptoms: `PAYLOAD_NOT_FORWARDED`, `Cannot receive SBI message`, UE registration fails with `UE_IDENTITY_CANNOT_BE_DERIVED_FROM_NETWORK`.

**Fix:** Nuclear restart — delete ALL pods at once so NRF re-registers everything cleanly:
```bash
kubectl delete pods --all -n open5gs
# Wait 60-90 seconds for all NFs to restart and re-register with NRF
sleep 90
kubectl get pods -n open5gs
```

### MongoDB has no persistent volume by default
The Gradiant chart deploys MongoDB with emptyDir. If the MongoDB pod restarts, **all subscribers are lost**. For production, add a PVC:
```bash
helm upgrade open5gs gradiant/open5gs -n open5gs --set mongodb.persistence.enabled=true
```

## Troubleshooting

| Issue | Check | Fix |
|-------|-------|-----|
| PCRF CrashLoopBackOff | Expected for 5G SA | `kubectl scale deploy open5gs-pcrf -n open5gs --replicas=0` |
| NFs can't register with NRF | NRF pod running? | Check NRF logs, restart NRF first |
| SBI mesh broken after restarts | SCP caching stale endpoints | Nuclear restart all pods |
| MongoDB image pull failure | bitnami registry down | Override to `mongo:7.0` |

## Related SOPs
- **Next:** `day1-deploy/deploy-upf.md`
- **Next:** `day1-deploy/add-subscriber.md`
