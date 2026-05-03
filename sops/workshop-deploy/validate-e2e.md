# Validate End-to-End 5G SA Connectivity

**Duration:** ~10 minutes
**Target:** Full 5G SA stack (UE → gNB → Core → UPF)

## Overview
Deploy UERANSIM gNB and UE with SST:1 (no SD), validate registration, PDU session, and IP connectivity.

## Prerequisites
- 5G Core deployed and all NFs Running (deploy-5g-core.md completed)
- Subscribers inserted via mongosh with matching keys
- PFCP association confirmed

> **CRITICAL: Do NOT restart any open5gs pods during this SOP.**

## Steps

### Step 1: Create RAN namespace
```tool: kubectl
kubectl create namespace srsran --dry-run=client -o yaml | kubectl apply -f -
```
**Expected**: `namespace/srsran created`

### Step 2: Add SCTP security group rule
```tool: shell
NODE_ID=$(kubectl get nodes -o jsonpath='{.items[0].spec.providerID}' | awk -F/ '{print $NF}') && NODE_SG=$(aws ec2 describe-instances --instance-ids $NODE_ID --query 'Reservations[0].Instances[0].SecurityGroups[0].GroupId' --output text) && echo "Node SG: $NODE_SG" && aws ec2 authorize-security-group-ingress --group-id $NODE_SG --protocol 132 --port 0-65535 --source-group $NODE_SG 2>/dev/null && echo "SCTP rule added" || echo "SCTP rule already exists"
```
**Expected**: `SCTP rule added` or `SCTP rule already exists`

### Step 3: Get AMF pod IP
```tool: kubectl
AMF_POD_IP=$(kubectl get pod -n open5gs -l app.kubernetes.io/name=amf -o jsonpath='{.items[0].status.podIP}') && echo "AMF Pod IP: $AMF_POD_IP"
```
**Expected**: Pod IP (e.g., `10.0.11.57`)

### Step 4: Deploy UERANSIM gNB + UE (no SD, matching core config)
```tool: shell
helm upgrade --install ueransim oci://registry-1.docker.io/gradiant/ueransim-gnb --version 0.2.6 --namespace srsran --set amf.ip=$AMF_POD_IP --set-string mcc=999 --set-string mnc=70 --set sst=1 --set sd=0xffffff --set ues.enabled=true --set ues.count=1 --timeout 120s
```
**Expected**: `STATUS: deployed`

> **Note:** We use `sd=0xffffff` (no specific SD) to match the AMF default config (SST:1 only). We use `--set-string` for mcc/mnc to avoid Helm type errors. We use `amf.ip` (pod IP) because VPC CNI doesn't support SCTP for ClusterIP.

### Step 5: Verify gNB NG Setup
```tool: shell
sleep 25 && kubectl logs deploy/ueransim-ueransim-gnb -n srsran --tail=10
```
**Expected**: `NG Setup procedure is successful`

### Step 6: Fix UE session SD if needed
The Helm chart may hardcode `sd: 0x111111` in the UE sessions block. Patch it to match:
```tool: shell
kubectl get configmap ueransim-ueransim-gnb-ues -n srsran -o json | python3 -c "import sys,json; cm=json.load(sys.stdin); ue=cm['data']['ue.yaml']; ue=ue.replace('sd: \"0x111111\"','sd: \"0xffffff\"'); cm['data']['ue.yaml']=ue; json.dump(cm,sys.stdout)" | kubectl apply -f - && kubectl rollout restart deployment/ueransim-ueransim-gnb-ues -n srsran
```
**Expected**: `configmap configured`, `deployment restarted`

### Step 7: Verify UE registration and PDU session
```tool: shell
sleep 25 && kubectl logs deploy/ueransim-ueransim-gnb-ues -n srsran --tail=15
```
**Expected**:
- `Initial Registration is successful`
- `PDU Session establishment is successful PSI[1]`
- `TUN interface[uesimtun0, 10.45.0.x] is up`

### Step 8: Verify IP connectivity
```tool: kubectl
kubectl exec deploy/ueransim-ueransim-gnb-ues -n srsran -- ip addr show uesimtun0 2>/dev/null | grep inet
```
**Expected**: `inet 10.45.0.x/32`

## Troubleshooting

### UE_IDENTITY_CANNOT_BE_DERIVED_FROM_NETWORK
1. Verify subscribers exist with correct keys in MongoDB
2. Wait 2-3 minutes and restart UE pods only: `kubectl delete pods -l app.kubernetes.io/component=ues -n srsran && sleep 30`
3. Last resort: `kubectl delete pods --all -n open5gs && sleep 90`, re-insert subscribers, redeploy UERANSIM with fresh AMF IP

### No cells in coverage
UE started before gNB connected. Restart UE pods only: `kubectl delete pods -l app.kubernetes.io/component=ues -n srsran && sleep 30`

### DNN_NOT_SUPPORTED
Session SD mismatch. Step 6 should fix this. Verify UE configmap has `sd: "0xffffff"` in sessions block.

## Related SOPs
- **Previous:** `workshop-deploy/deploy-5g-core.md`
