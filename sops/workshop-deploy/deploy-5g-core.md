# Deploy 5G Core Network (Open5GS)

**Duration:** ~10 minutes
**Target:** EKS cluster

## Overview
Deploy Open5GS 5G SA core using Gradiant's official 5gSA values file. This disables all 4G components and configures the 5G SA core with matching slice configuration (SST:1, SD:0x111111).

## Prerequisites
- kubectl access to EKS cluster
- Helm 3 installed

## Steps

### Step 1: Create namespace
```tool: kubectl
kubectl create namespace open5gs --dry-run=client -o yaml | kubectl apply -f -
```
**Expected**: `namespace/open5gs created`

### Step 2: Deploy Open5GS 5G SA core
```tool: shell
helm upgrade --install open5gs oci://registry-1.docker.io/gradiantcharts/open5gs --version 2.3.4 --namespace open5gs --values https://gradiant.github.io/5g-charts/docs/open5gs-ueransim-gnb/5gSA-values.yaml --set mongodb.persistence.enabled=false --set mongodb.auth.enabled=false --timeout 600s
```
**Expected**: `STATUS: deployed`

### Step 3: Wait for core NFs
```tool: kubectl
kubectl wait --for=condition=ready pod -l app.kubernetes.io/name=nrf -n open5gs --timeout=180s && kubectl wait --for=condition=ready pod -l app.kubernetes.io/name=amf -n open5gs --timeout=180s && kubectl wait --for=condition=ready pod -l app.kubernetes.io/name=mongodb -n open5gs --timeout=180s && kubectl wait --for=condition=ready pod -l app.kubernetes.io/name=upf -n open5gs --timeout=180s
```
**Expected**: All report `condition met`

### Step 4: Nuclear restart to establish clean SBI mesh
The Helm chart starts all NFs simultaneously. The SCP caches NF endpoints during startup which can become stale. A nuclear restart forces all NFs to re-register with NRF cleanly, establishing proper SBI communication and PFCP associations.
```tool: kubectl
kubectl delete pods --all -n open5gs
```
**Expected**: All pods deleted

### Step 5: Wait for all NFs to restart and stabilize
```tool: shell
sleep 90 && kubectl wait --for=condition=ready pod --all -n open5gs --timeout=180s
```
**Expected**: All pods ready after 90 second stabilization period

### Step 6: Verify all pods running
```tool: kubectl
kubectl get pods -n open5gs --no-headers | awk '{print $1, $3}' | column -t
```
**Expected**: All pods Running. No PCRF/MME/SGWC/SGWU/HSS pods (disabled by 5gSA-values.yaml).

### Step 7: Verify PFCP association
```tool: kubectl
kubectl logs -l app.kubernetes.io/name=smf -n open5gs --tail=10 | grep -i pfcp
```
**Expected**: `PFCP associated` message

> **Troubleshooting:** If no PFCP message, wait 30 more seconds and check again. The nuclear restart ensures SMF and UPF start fresh and discover each other via NRF.

## Known Issues

### SMF crashes with fd_init assertion
Should not happen with 5gSA-values.yaml (Diameter disabled). If it does, the values file was not applied correctly.

### Pods stuck in Pending
Check node resources: `kubectl describe nodes | grep -A5 "Allocated resources"`

## Related SOPs
- **Next:** `workshop-deploy/validate-e2e.md`
