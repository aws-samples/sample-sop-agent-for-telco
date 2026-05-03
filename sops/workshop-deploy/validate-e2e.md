# Validate End-to-End 5G SA Connectivity

**Duration:** ~10 minutes
**Target:** Full 5G SA stack (UE → gNB → Core → UPF)

## Overview
Deploy UERANSIM gNB and UE, validate registration, authentication, PDU session, and IP connectivity.

## Prerequisites
- 5G Core deployed with 5gSA-values.yaml (all NFs Running)
- Subscribers pre-registered by populate container (IMSI 999700000000001)

> **CRITICAL: Never restart individual NFs (e.g., AUSF, UDM) during troubleshooting. The SCP caches NF endpoints and individual restarts break the SBI mesh. If anything fails, always do a full nuclear restart: `kubectl delete pods --all -n open5gs && sleep 90`**

## Steps

### Step 1: Create RAN namespace
```tool: kubectl
kubectl create namespace srsran --dry-run=client -o yaml | kubectl apply -f -
```
**Expected**: `namespace/srsran created`

### Step 2: Ensure SCTP is allowed in node security groups
```tool: shell
NODE_ID=$(kubectl get nodes -o jsonpath='{.items[0].spec.providerID}' | awk -F/ '{print $NF}') && NODE_SG=$(aws ec2 describe-instances --instance-ids $NODE_ID --query 'Reservations[0].Instances[0].SecurityGroups[0].GroupId' --output text) && echo "Node SG: $NODE_SG" && aws ec2 authorize-security-group-ingress --group-id $NODE_SG --protocol 132 --port 0-65535 --source-group $NODE_SG 2>/dev/null && echo "SCTP rule added" || echo "SCTP rule already exists"
```
**Expected**: `SCTP rule added` or `SCTP rule already exists`

### Step 3: Nuclear restart Open5GS to ensure clean SBI mesh
```tool: shell
kubectl delete pods --all -n open5gs && echo "Waiting 90s for SBI mesh to stabilize..." && sleep 90 && kubectl wait --for=condition=ready pod --all -n open5gs --timeout=180s && echo "All NFs ready"
```
**Expected**: All pods ready after stabilization

> **Why:** The SBI mesh (SCP→NRF→AUSF→UDM→UDR) must be fully converged before UE authentication will work. AUSF returns HTTP 500 if the SBI mesh has stale endpoints.

### Step 4: Verify PFCP association
```tool: kubectl
kubectl logs -l app.kubernetes.io/name=smf -n open5gs --tail=10 | grep -i pfcp
```
**Expected**: `PFCP associated`

### Step 5: Get AMF pod IP (MUST be after nuclear restart — pods have new IPs)
```tool: kubectl
AMF_POD_IP=$(kubectl get pod -n open5gs -l app.kubernetes.io/name=amf -o jsonpath='{.items[0].status.podIP}') && echo "AMF Pod IP: $AMF_POD_IP"
```
**Expected**: Pod IP (e.g., `10.0.11.57`)

> **Critical:** This MUST be done AFTER the nuclear restart in Step 3. The restart creates new pods with new IPs. Using a stale AMF IP will cause the gNB SCTP connection to be terminated.

### Step 6: Verify gNB and UE configs before deploying
Check that the gnb-ues-values.yaml has correct slice config and credentials:
```tool: shell
curl -s https://gradiant.github.io/5g-charts/docs/open5gs-ueransim-gnb/gnb-ues-values.yaml | grep -E "mcc|mnc|sst|sd|key|opc|supi"
```
**Expected**: mcc=999, mnc=70, sst=1, sd=0x111111, key and opc matching subscriber in MongoDB

### Step 7: Deploy UERANSIM gNB + UE
```tool: shell
helm upgrade --install ueransim oci://registry-1.docker.io/gradiant/ueransim-gnb --version 0.2.6 --namespace srsran --values https://gradiant.github.io/5g-charts/docs/open5gs-ueransim-gnb/gnb-ues-values.yaml --set amf.ip=$AMF_POD_IP --timeout 120s
```
**Expected**: `STATUS: deployed`

### Step 8: Verify gNB NG Setup
```tool: kubectl
sleep 20 && kubectl logs deploy/ueransim-ueransim-gnb -n srsran --tail=10
```
**Expected**: `NG Setup procedure is successful`

> **Troubleshooting:**
> - `SCTP could not connect` → SG rule missing (Step 2) or AMF IP is stale (redo Step 5)
> - `slice-not-supported` → SD mismatch between gNB and AMF config

### Step 9: Verify UE registration and PDU session
```tool: kubectl
sleep 15 && kubectl logs deploy/ueransim-ueransim-gnb-ues -n srsran --tail=15
```
**Expected**:
- `Initial Registration is successful`
- `PDU Session establishment is successful PSI[1]`
- `TUN interface[uesimtun0, 10.45.0.x] is up`

> **Troubleshooting:**
> - `UE_IDENTITY_CANNOT_BE_DERIVED_FROM_NETWORK` → SBI mesh is stale. Do NOT restart individual NFs. Nuclear restart: `kubectl delete pods --all -n open5gs && sleep 90` then `kubectl delete pods --all -n srsran && sleep 20`
> - `no cells in coverage` → gNB lost AMF connection. AMF IP may have changed. Redo Steps 3-7.

### Step 10: Verify IP connectivity
```tool: kubectl
kubectl exec deploy/ueransim-ueransim-gnb-ues -n srsran -- ip addr show uesimtun0 2>/dev/null | grep inet
```
**Expected**: `inet 10.45.0.x/32`

## Related SOPs
- **Previous:** `workshop-deploy/deploy-5g-core.md`
- **Remediation:** `workshop-remediate/remediate-nf-crashloop.md`
