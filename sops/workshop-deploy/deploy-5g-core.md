# Deploy 5G Core Network (Open5GS)

**Duration:** ~10 minutes
**Target:** EKS cluster

## Overview
Deploy Open5GS 5G SA core with individual Helm values (no 5gSA-values.yaml). Uses SST:1 with no SD to avoid known AUSF SUCI decryption issues.

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
helm upgrade --install open5gs oci://registry-1.docker.io/gradiantcharts/open5gs --version 2.3.4 --namespace open5gs --set populate.enabled=true --set mongodb.persistence.enabled=false --set mongodb.auth.enabled=false --set upf.enabled=true --set webui.enabled=true --set pcrf.enabled=false --set mme.enabled=false --set sgwc.enabled=false --set sgwu.enabled=false --set hss.enabled=false --set smf.config.pcrf.enabled=false --timeout 600s
```
**Expected**: `STATUS: deployed`

> **Note:** We disable all 4G NFs and Diameter in SMF. We do NOT use 5gSA-values.yaml because it sets sd:0x111111 which triggers a known AUSF SUCI decryption bug in Open5GS 2.7.5.

### Step 3: Wait for MongoDB first
```tool: kubectl
kubectl wait --for=condition=ready pod -l app.kubernetes.io/name=mongodb -n open5gs --timeout=180s
```
**Expected**: `condition met`

### Step 4: Wait for NFs to stabilize
```tool: shell
sleep 60 && kubectl get pods -n open5gs --no-headers | awk '{print $1, $3, $4}' | column -t
```
**Expected**: Most pods Running. Some may show 1-3 restarts — normal during initial convergence.

### Step 5: Wait for all pods ready
```tool: kubectl
kubectl wait --for=condition=ready pod --all -n open5gs --timeout=180s
```
**Expected**: All pods report `condition met`

### Step 6: Verify PFCP association
```tool: shell
sleep 10 && kubectl logs -l app.kubernetes.io/name=smf -n open5gs --tail=10 | grep -i "pfcp"
```
**Expected**: `PFCP associated`

> **If no PFCP:** Restart SMF: `kubectl delete pod -l app.kubernetes.io/name=smf -n open5gs` and wait 30 seconds.

### Step 7: Insert subscribers with UERANSIM-matching keys
```tool: shell
MONGO=$(kubectl get pods -l app.kubernetes.io/name=mongodb -n open5gs --no-headers | grep Running | awk '{print $1}') && kubectl exec $MONGO -n open5gs -- mongosh open5gs --quiet --eval 'db.subscribers.deleteMany({}); db.subscribers.insertOne({"imsi":"999700000000001","msisdn":[],"security":{"k":"465B5CE8B199B49FAA5F0A2EE238A6BC","amf":"8000","op":null,"opc":"E8ED289DEBA952E4283B54E88E6183CA"},"ambr":{"downlink":{"value":1,"unit":3},"uplink":{"value":1,"unit":3}},"slice":[{"sst":1,"default_indicator":true,"session":[{"name":"internet","type":3,"ambr":{"downlink":{"value":1,"unit":3},"uplink":{"value":1,"unit":3}},"qos":{"index":9,"arp":{"priority_level":8,"pre_emption_capability":1,"pre_emption_vulnerability":1}}}]}]}); db.subscribers.insertOne({"imsi":"999700000000002","msisdn":[],"security":{"k":"465B5CE8B199B49FAA5F0A2EE238A6BC","amf":"8000","op":null,"opc":"E8ED289DEBA952E4283B54E88E6183CA"},"ambr":{"downlink":{"value":1,"unit":3},"uplink":{"value":1,"unit":3}},"slice":[{"sst":1,"default_indicator":true,"session":[{"name":"internet","type":3,"ambr":{"downlink":{"value":1,"unit":3},"uplink":{"value":1,"unit":3}},"qos":{"index":9,"arp":{"priority_level":8,"pre_emption_capability":1,"pre_emption_vulnerability":1}}}]}]}); print("Subscribers: " + db.subscribers.countDocuments())'
```
**Expected**: `Subscribers: 2`

> **Critical:** Subscribers use SST:1 with NO SD (matching the default AMF config). Keys match UERANSIM chart defaults (K=465B5CE8..., OPC=E8ED289D...).

### Step 8: Verify all pods running
```tool: kubectl
kubectl get pods -n open5gs --no-headers | awk '{print $1, $3}' | column -t
```
**Expected**: All pods Running.

## Known Issues

### SMF crashes with fd_init assertion
The `smf.config.pcrf.enabled=false` flag should prevent this. If SMF still crashes, upgrade: `helm upgrade open5gs ... --reuse-values --set smf.config.pcrf.enabled=false`

### Individual NF restarts break SBI mesh
Do NOT restart individual NFs. If SBI mesh breaks, restart ALL pods: `kubectl delete pods --all -n open5gs && sleep 90`

## Related SOPs
- **Next:** `workshop-deploy/validate-e2e.md`
