# Validate End-to-End 5G SA Connectivity

**Duration:** ~5 minutes
**Target:** Full 5G SA stack (UE → gNB → Core)

## Overview
Validate the complete 5G SA signaling chain: UE registration, authentication, PDU session establishment, and IP connectivity through the UPF. Uses UERANSIM as the UE/gNB simulator.

## Prerequisites
- 5G Core deployed and healthy (all NFs Running)
- UPF deployed with PFCP association confirmed
- Subscriber added to MongoDB with matching K/OPC
- UERANSIM images available (`openverso/ueransim:3.2.6`)

## Steps

### Step 1: Deploy UERANSIM gNB
```bash
GNB_CONFIG=$(cat <<'YAML'
mcc: '999'
mnc: '70'
nci: '0x000000010'
idLength: 32
tac: 1
linkIp: 0.0.0.0
ngapIp: 0.0.0.0
gtpIp: 0.0.0.0
amfConfigs:
  - address: AMF_SERVICE_ADDRESS
    port: 38412
slices:
  - sst: 1
ignoreStreamIds: true
YAML
)

kubectl create configmap ueransim-gnb-config -n ran --from-literal=gnb.yaml="$GNB_CONFIG" --dry-run=client -o yaml | kubectl apply -f -

kubectl apply -f - <<EOF
apiVersion: v1
kind: Pod
metadata:
  name: ueransim-gnb
  namespace: ran
  labels:
    app: ueransim-gnb
spec:
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
      name: ueransim-gnb-config
EOF
```
**Expected**: `pod/ueransim-gnb created`

### Step 2: Verify gNB connected to AMF
```bash
sleep 10
kubectl logs ueransim-gnb -n ran | grep "NG Setup"
```
**Expected**: `NG Setup procedure is successful`

### Step 3: Get gNB pod IP (needed for UE config)
```bash
GNB_IP=$(kubectl get pod ueransim-gnb -n ran -o jsonpath='{.status.podIP}')
echo "gNB IP: $GNB_IP"
```
**Expected**: Pod IP address (e.g., `10.100.1.159`)

> **Critical:** The UE's `gnbSearchList` must match this IP exactly. If the gNB pod restarts and gets a new IP, the UE config must be updated.

### Step 4: Deploy UERANSIM UE
```bash
UE_CONFIG=$(cat <<YAML
supi: 'imsi-IMSI_VALUE'
mcc: '999'
mnc: '70'
key: 'K_VALUE'
op: 'OPC_VALUE'
opType: 'OPC'
amf: '8000'
imei: '356938035643803'
imeiSv: '4370816125816151'
gnbSearchList:
  - ${GNB_IP}
sessions:
  - type: 'IPv4'
    apn: 'APN_NAME'
    slice:
      sst: 1
configured-nssai:
  - sst: 1
default-nssai:
  - sst: 1
integrity:
  IA1: true
  IA2: true
  IA3: true
ciphering:
  EA1: true
  EA2: true
  EA3: true
integrityMaxRate:
  uplink: 'full'
  downlink: 'full'
YAML
)

kubectl create configmap ueransim-ue-config -n ran --from-literal=ue.yaml="$UE_CONFIG" --dry-run=client -o yaml | kubectl apply -f -

kubectl apply -f - <<EOF
apiVersion: v1
kind: Pod
metadata:
  name: ueransim-ue
  namespace: ran
  labels:
    app: ueransim-ue
spec:
  containers:
  - name: ue
    image: openverso/ueransim:3.2.6
    command: ["nr-ue"]
    args: ["-c", "/config/ue.yaml"]
    securityContext:
      privileged: true
    volumeMounts:
    - name: config
      mountPath: /config
    - name: tun
      mountPath: /dev/net/tun
  volumes:
  - name: config
    configMap:
      name: ueransim-ue-config
  - name: tun
    hostPath:
      path: /dev/net/tun
      type: CharDevice
EOF
```
**Expected**: `pod/ueransim-ue created`

> **Critical UE config fields that are often missing:**
> - `integrity` (IA1/IA2/IA3) — without these, security mode command fails
> - `ciphering` (EA1/EA2/EA3) — without these, NAS encryption fails
> - `integrityMaxRate` — without this, the UE rejects the security context
> - `opType: 'OPC'` — must be OPC not OP if using operator key
> - `/dev/net/tun` mount + privileged — without these, TUN interface creation fails and there's no data plane

### Step 5: Verify UE registration and PDU session
```bash
sleep 20
kubectl logs ueransim-ue -n ran | grep -E "Registration is successful|PDU Session|TUN interface"
```
**Expected**:
```
Initial Registration is successful
PDU Session establishment is successful PSI[1]
Connection setup for PDU session[1] is successful, TUN interface[uesimtun0, 10.45.0.x] is up.
```

### Step 6: Verify AMF sees the gNB and UE
```bash
kubectl logs -l app.kubernetes.io/name=amf -n open5gs | grep "Number of" | tail -2
```
**Expected**: `Number of gNBs is now 1` and `Number of AMF-UEs is now 1`

## Verification

### Final Check — Complete E2E signaling path
```bash
echo "=== Registration ==="
kubectl logs ueransim-ue -n ran | grep "Registration"
echo "=== PDU Session ==="
kubectl logs ueransim-ue -n ran | grep "PDU Session"
echo "=== IP Address ==="
kubectl logs ueransim-ue -n ran | grep "TUN interface"
```
**Expected**: All three successful. Registration ~91ms, PDU session ~2.7s.

## Known Issues

### gNB IP changes on pod restart
UERANSIM UE uses `gnbSearchList` to find the gNB. If the gNB pod restarts and gets a new IP, the UE will fail with `PLMN selection failure, no cells in coverage`. **Fix:** Update the UE configmap with the new gNB IP and restart the UE pod.

### Subscriber lost after MongoDB restart
If MongoDB restarts, the subscriber is deleted (no PVC by default). The UE will get `PLMN_NOT_ALLOWED`. **Fix:** Re-run `add-subscriber.md`.

### SBI mesh stale after NF restarts
If you restarted core NFs during troubleshooting, the SBI mesh may be broken. The UE will register but PDU session fails with `PAYLOAD_NOT_FORWARDED`. **Fix:** Nuclear restart all open5gs pods (see `deploy-5g-core.md` Known Issues).

### TUN allocation failure
If the UE logs show `TUN allocation failure [Open failure /dev/net/tun]`, the pod doesn't have access to the TUN device. **Fix:** Add `privileged: true` and mount `/dev/net/tun` as hostPath (shown in Step 4).

## Troubleshooting

| Issue | Check | Fix |
|-------|-------|-----|
| `no cells in coverage` | gNB IP matches gnbSearchList? | Update UE config with current gNB pod IP |
| `PLMN_NOT_ALLOWED` | Subscriber in MongoDB? | Re-run add-subscriber.md |
| `Authentication failure` | K/OPC match? | Verify hex values |
| PDU session fails | SMF→UPF PFCP active? | Check SMF logs for PFCP association |
| `TUN allocation failure` | Pod has /dev/net/tun? | Add privileged + hostPath mount |
| Registration OK but no PDU | SBI mesh broken? | Nuclear restart all open5gs pods |

## Related SOPs
- **Previous:** `day1-deploy/add-subscriber.md`
- **Previous:** `day1-deploy/deploy-ran-du.md`
