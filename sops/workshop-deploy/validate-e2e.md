# Validate End-to-End 5G SA Connectivity

**Duration:** ~10 minutes
**Target:** Full 5G SA stack (UE → gNB → Core → UPF)

## Overview
Deploy UERANSIM gNB and UE, validate registration, authentication, PDU session, and IP connectivity. Uses Gradiant's official gnb-ues-values.yaml which matches the 5gSA-values.yaml slice config (SST:1, SD:0x111111).

## Prerequisites
- 5G Core deployed with 5gSA-values.yaml (all NFs Running)
- Subscribers pre-registered by populate container (IMSI 999700000000001)

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

> **Critical:** EKS node security groups block SCTP (protocol 132) by default. Without this rule, the gNB SCTP connection to AMF will timeout after 5 minutes. This is the #1 deployment failure for 5G on EKS.

### Step 3: Get AMF pod IP
```tool: kubectl
AMF_POD_IP=$(kubectl get pod -n open5gs -l app.kubernetes.io/name=amf -o jsonpath='{.items[0].status.podIP}') && echo "AMF Pod IP: $AMF_POD_IP"
```
**Expected**: Pod IP (e.g., `10.0.11.57`)

> **Critical:** Use AMF pod IP, NOT ClusterIP service. AWS VPC CNI does not support SCTP for ClusterIP services.

### Step 4: Deploy UERANSIM gNB + UE
```tool: shell
helm upgrade --install ueransim oci://registry-1.docker.io/gradiant/ueransim-gnb --version 0.2.6 --namespace srsran --values https://gradiant.github.io/5g-charts/docs/open5gs-ueransim-gnb/gnb-ues-values.yaml --set amf.ip=$AMF_POD_IP --timeout 120s
```
**Expected**: `STATUS: deployed`

> **Note:** The gnb-ues-values.yaml sets mcc=999, mnc=70, sst=1, sd=0x111111 matching the 5gSA-values.yaml. It also deploys 2 UEs with matching subscriber credentials.

### Step 5: Verify gNB NG Setup
```tool: kubectl
sleep 20 && kubectl logs deploy/ueransim-ueransim-gnb -n srsran --tail=10
```
**Expected**: `NG Setup procedure is successful`

> **Troubleshooting:**
> - `SCTP could not connect: Connection timed out` → SCTP SG rule missing (Step 2)
> - `slice-not-supported` → SD mismatch. Verify both chart used 5gSA-values.yaml and gnb-ues-values.yaml

### Step 6: Verify UE registration and PDU session
```tool: kubectl
sleep 10 && kubectl logs deploy/ueransim-ueransim-gnb-ues -n srsran --tail=15
```
**Expected**:
- `Initial Registration is successful`
- `PDU Session establishment is successful PSI[1]`
- `TUN interface[uesimtun0, 10.45.0.x] is up`

> **Troubleshooting:**
> - `Authentication failure / SQN out of range` → Subscriber keys don't match UE. Re-deploy with matching values files.
> - `DNN_NOT_SUPPORTED` → Session slice SD doesn't match subscriber. Both should be 0x111111 from the values files.

### Step 7: Verify IP connectivity
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
- **Remediation:** `workshop-remediate/remediate-amf-gnb-disconnect.md`
