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

### Step 3: Nuclear restart Open5GS to ensure clean SBI mesh before UE registration
```tool: shell
kubectl delete pods --all -n open5gs && echo "Waiting 90s for SBI mesh to stabilize..." && sleep 90 && kubectl wait --for=condition=ready pod --all -n open5gs --timeout=180s && echo "All NFs ready"
```
**Expected**: All pods ready after stabilization

> **Why:** The SBI mesh (SCP→NRF→AUSF→UDM→UDR) must be fully converged before UE authentication will work. AUSF returns HTTP 500 if the SBI mesh has stale endpoints. A nuclear restart forces all NFs to re-register with NRF simultaneously.

### Step 4: Verify PFCP association
```tool: kubectl
kubectl logs -l app.kubernetes.io/name=smf -n open5gs --tail=10 | grep -i pfcp
```
**Expected**: `PFCP associated`

> **If no PFCP:** Wait 30 more seconds and check again. If still missing, repeat Step 3.

### Step 5: Get AMF pod IP
```tool: kubectl
AMF_POD_IP=$(kubectl get pod -n open5gs -l app.kubernetes.io/name=amf -o jsonpath='{.items[0].status.podIP}') && echo "AMF Pod IP: $AMF_POD_IP"
```
**Expected**: Pod IP (e.g., `10.0.11.57`)

> **Critical:** Use AMF pod IP, NOT ClusterIP service. AWS VPC CNI does not support SCTP for ClusterIP services.

### Step 6: Deploy UERANSIM gNB + UE
```tool: shell
helm upgrade --install ueransim oci://registry-1.docker.io/gradiant/ueransim-gnb --version 0.2.6 --namespace srsran --values https://gradiant.github.io/5g-charts/docs/open5gs-ueransim-gnb/gnb-ues-values.yaml --set amf.ip=$AMF_POD_IP --timeout 120s
```
**Expected**: `STATUS: deployed`

### Step 7: Verify gNB NG Setup
```tool: kubectl
sleep 20 && kubectl logs deploy/ueransim-ueransim-gnb -n srsran --tail=10
```
**Expected**: `NG Setup procedure is successful`

> **Troubleshooting:**
> - `SCTP could not connect: Connection timed out` → SCTP SG rule missing (go back to Step 2)
> - `slice-not-supported` → SD mismatch. Both charts should use gnb-ues-values.yaml and 5gSA-values.yaml which have matching SD:0x111111

### Step 8: Verify UE registration and PDU session
```tool: kubectl
sleep 15 && kubectl logs deploy/ueransim-ueransim-gnb-ues -n srsran --tail=15
```
**Expected**:
- `Initial Registration is successful`
- `PDU Session establishment is successful PSI[1]`
- `TUN interface[uesimtun0, 10.45.0.x] is up`

> **Troubleshooting:**
> - `UE_IDENTITY_CANNOT_BE_DERIVED_FROM_NETWORK` → SBI mesh is stale. Do NOT restart individual NFs. Instead: `kubectl delete pods --all -n open5gs && sleep 90` then restart UE pods: `kubectl delete pods --all -n srsran && sleep 20`
> - `Authentication failure / SQN out of range` → Subscriber keys don't match UE. Both should come from the official values files.
> - `DNN_NOT_SUPPORTED` → Session slice SD doesn't match subscriber. Both should be 0x111111 from the values files.

### Step 9: Verify IP connectivity
```tool: kubectl
kubectl exec deploy/ueransim-ueransim-gnb-ues -n srsran -- ip addr show uesimtun0 2>/dev/null | grep inet
```
**Expected**: `inet 10.45.0.x/32` — UE has IP via UPF tunnel

## Verification
```tool: kubectl
echo "=== ALL PODS ===" && kubectl get pods -n open5gs --no-headers | awk '{print $1,$3}' && echo "=== UERANSIM ===" && kubectl get pods -n srsran --no-headers | awk '{print $1,$3}'
```
**Expected**: All pods Running across both namespaces

## Related SOPs
- **Previous:** `workshop-deploy/deploy-5g-core.md`
- **Remediation:** `workshop-remediate/remediate-nf-crashloop.md`
