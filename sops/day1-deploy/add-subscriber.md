# Add Subscriber to Free5GC

**Duration:** ~3 minutes
**Target:** Free5GC WebUI API (`free5gc-webui:5000`) → MongoDB database `free5gc`, namespace `free5gc`

## Overview
Provision a UE subscriber (SUPI/IMSI, 5G-AKA keys K and OPc, default slices and DNN) so a UE can register with the Free5GC core. Free5GC stores subscribers in MongoDB, but the supported write path is the WebUI's REST API: it validates the record and writes the `AuthenticationSubscription`, `AccessAndMobilitySubscriptionData`, `SessionManagementSubscriptionData` and policy documents consistently across collections. Do not insert into MongoDB directly.

The workshop chart already provisions 500 subscribers at install time through the `subprov` Job (IMSI `208930000000003`–`208930000000502`, PLMN `20893`, K `8baf473f2f8fd09487cccbd7097c6862`, OPc `8e27b6af0e692e750f32667a3b14605d`, slices SST 1 / SD `010203` and `112233`, DNNs `internet` and `internet2`). PacketRusher uses the first one (MSIN `0000000003`). Use this SOP to add a subscriber outside that range — a second simulated UE, for example — or to restore a single deleted one.

If **all** subscribers are missing (typically because the MongoDB pod was recreated and its `emptyDir` storage was lost), do not add them one by one: re-run the `subprov` Job as described in `day2-remediate/core/free5gc-registration-unavailable.md`, Step 3c.

## Prerequisites
- Free5GC deployed in namespace `free5gc`; `free5gc-webui`, `free5gc-mongodb` and `free5gc-udr-deployment` Running
- WebUI admin credentials (chart defaults `admin` / `free5gc`; confirm with `helm get values free5gc -n free5gc -a | grep -A3 subprov`)
- Subscriber values: IMSI (15 digits, `<MCC><MNC><MSIN>`, e.g. `208930000000503`), K and OPc (32 hex chars each), MSISDN
- K, OPc, PLMN, slice and DNN must match the UE's configuration exactly (for PacketRusher: `kubectl get configmap packetrusher-packetrusher -n free5gc -o yaml`)

## Steps

### Step 1: Confirm the WebUI is reachable and log in
Run the API calls from a short-lived helper pod inside the cluster so the WebUI ClusterIP Service resolves; `badouralix/curl-jq` is the image the chart's `subprov` Job uses.
```bash
kubectl run subadd --rm -i --restart=Never -n free5gc --image=badouralix/curl-jq -- sh -c '
set -e
BASE=http://free5gc-webui:5000
curl -sSf "$BASE" >/dev/null && echo "webui reachable"
TOKEN=$(curl -sfS -X POST "$BASE/api/login" -H "Content-Type: application/json" \
  -d "{\"username\":\"admin\",\"password\":\"free5gc\"}" | jq -r ".token // .accessToken // .access_token")
echo "token segments: $(printf %s "$TOKEN" | awk -F. "{print NF}")"
'
```
**Expected**: `webui reachable` and `token segments: 3` (a JWT). HTTP `401` means the admin password differs from the chart default.

### Step 2: Add the subscriber
Replace the four `CHANGE_ME` values. The payload mirrors the chart's `subprov` Job (5G-AKA, Milenage with OPc, two default slices, DNNs `internet` and `internet2`, 5QI 9) so the new subscriber behaves exactly like the pre-provisioned ones. Keep slices and DNNs unless the UE uses different ones — they must also exist in the SMF/NSSF configuration.
```bash
IMSI=CHANGE_ME_208930000000503
MSISDN=CHANGE_ME_9000000503
K=CHANGE_ME_8baf473f2f8fd09487cccbd7097c6862
OPC=CHANGE_ME_8e27b6af0e692e750f32667a3b14605d
PLMN=20893

kubectl run subadd --rm -i --restart=Never -n free5gc --image=badouralix/curl-jq \
  --env IMSI="$IMSI" --env MSISDN="$MSISDN" --env K="$K" --env OPC="$OPC" --env PLMN="$PLMN" -- sh -c '
set -e
BASE=http://free5gc-webui:5000
TOKEN=$(curl -sfS -X POST "$BASE/api/login" -H "Content-Type: application/json" \
  -d "{\"username\":\"admin\",\"password\":\"free5gc\"}" | jq -r ".token // .accessToken // .access_token")
DNNCFG=$(cat <<EOF
{"sscModes":{"defaultSscMode":"SSC_MODE_1","allowedSscModes":["SSC_MODE_2","SSC_MODE_3"]},
 "pduSessionTypes":{"defaultSessionType":"IPV4","allowedSessionTypes":["IPV4"]},
 "sessionAmbr":{"uplink":"200 Mbps","downlink":"100 Mbps"},
 "5gQosProfile":{"5qi":9,"arp":{"priorityLevel":8},"priorityLevel":8}}
EOF
)
BODY=$(cat <<EOF
{
  "plmnID": "$PLMN",
  "ueId": "imsi-$IMSI",
  "AuthenticationSubscription": {
    "authenticationManagementField": "8000",
    "authenticationMethod": "5G_AKA",
    "milenage": {"op": {"encryptionAlgorithm": 0, "encryptionKey": 0, "opValue": ""}},
    "opc": {"encryptionAlgorithm": 0, "encryptionKey": 0, "opcValue": "$OPC"},
    "permanentKey": {"encryptionAlgorithm": 0, "encryptionKey": 0, "permanentKeyValue": "$K"},
    "sequenceNumber": "000000000023"
  },
  "AccessAndMobilitySubscriptionData": {
    "gpsis": ["msisdn-$MSISDN"],
    "nssai": {
      "defaultSingleNssais": [
        {"sst": 1, "sd": "010203", "isDefault": true},
        {"sst": 1, "sd": "112233", "isDefault": true}
      ],
      "singleNssais": []
    },
    "subscribedUeAmbr": {"downlink": "2 Gbps", "uplink": "1 Gbps"}
  },
  "SessionManagementSubscriptionData": [
    {"singleNssai": {"sst": 1, "sd": "010203"}, "dnnConfigurations": {"internet": $DNNCFG, "internet2": $DNNCFG}},
    {"singleNssai": {"sst": 1, "sd": "112233"}, "dnnConfigurations": {"internet": $DNNCFG, "internet2": $DNNCFG}}
  ],
  "SmfSelectionSubscriptionData": {
    "subscribedSnssaiInfos": {
      "01010203": {"dnnInfos": [{"dnn": "internet"}, {"dnn": "internet2"}]},
      "01112233": {"dnnInfos": [{"dnn": "internet"}, {"dnn": "internet2"}]}
    }
  },
  "AmPolicyData": {"subscCats": ["free5gc"]},
  "SmPolicyData": {
    "smPolicySnssaiData": {
      "01010203": {"snssai": {"sst": 1, "sd": "010203"}, "smPolicyDnnData": {"internet": {"dnn": "internet"}, "internet2": {"dnn": "internet2"}}},
      "01112233": {"snssai": {"sst": 1, "sd": "112233"}, "smPolicyDnnData": {"internet": {"dnn": "internet"}, "internet2": {"dnn": "internet2"}}}
    }
  },
  "FlowRules": [
    {"snssai": "01010203", "dnn": "internet", "filter": "permit out 17 from 192.168.0.0/24 8000 to 60.60.0.0/24 ", "precedence": 1, "qfi": 5}
  ],
  "QosFlows": [
    {"qfi": 5, "5qi": 5, "snssai": "01010203", "dnn": "internet", "gbrUL": "", "gbrDL": "", "mbrUL": "200 Mbps", "mbrDL": "100 Mbps"}
  ]
}
EOF
)
CODE=$(curl -s -o /tmp/resp -w "%{http_code}" -X POST "$BASE/api/subscriber/imsi-$IMSI/$PLMN" \
  -H "Token: $TOKEN" -H "Content-Type: application/json" -d "$BODY")
echo "HTTP $CODE"; cat /tmp/resp; echo
[ "$CODE" -lt 400 ]
'
```
**Expected**: `HTTP 201` (or `200`) with an empty or `{}` body. A `4xx`/`5xx` mentioning "already exists" means the subscriber is present — remove it first (Rollback) or treat as success. A `400` names the invalid field.

### Step 3: Verify through the API
```bash
kubectl run subadd --rm -i --restart=Never -n free5gc --image=badouralix/curl-jq --env IMSI="$IMSI" --env PLMN="$PLMN" -- sh -c '
BASE=http://free5gc-webui:5000
TOKEN=$(curl -sfS -X POST "$BASE/api/login" -H "Content-Type: application/json" -d "{\"username\":\"admin\",\"password\":\"free5gc\"}" | jq -r ".token // .accessToken // .access_token")
curl -sS "$BASE/api/subscriber/imsi-$IMSI/$PLMN" -H "Token: $TOKEN" \
  | jq "{ueId, plmnID, k: .AuthenticationSubscription.permanentKey.permanentKeyValue, slices: [.SessionManagementSubscriptionData[].singleNssai.sd]}"
echo "total subscribers: $(curl -sS "$BASE/api/subscriber" -H "Token: $TOKEN" | jq length)"
'
```
**Expected**: the record with your IMSI, PLMN, K and `"slices": ["010203", "112233"]`; total is 501 if the chart's 500 are still present.

### Step 4: Register a UE with the new subscriber (optional)
For a second PacketRusher instance, clone the `packetrusher` release with the new MSIN/keys and distinct N2/N3 Multus addresses (each PacketRusher pod owns a static IP on both networks):
```bash
helm get values packetrusher -n free5gc -o yaml > /tmp/pr2-values.yaml
# edit /tmp/pr2-values.yaml:
#   config.ue.msin  -> last 10 digits of IMSI      config.ue.key / config.ue.opc -> K / OPC
#   config.n2network.ipAddress, config.n3network.ipAddress -> unused addresses in the N2/N3 subnets
helm install packetrusher2 /app/helm-charts/free5gc-bundle/packetrusher-0.0.3.tgz -n free5gc -f /tmp/pr2-values.yaml
kubectl rollout status deploy packetrusher2-packetrusher -n free5gc --timeout=120s
kubectl logs -n free5gc deploy/packetrusher2-packetrusher --tail=30 | grep -iE "Registration|PDU"
```
**Expected**: `Registration accept` and `PDU Session Establishment Accept`; `free5gc_amf_business_ue_gmm_state_count{gmm_state="Registered"}` rises by one.

## Rollback
```bash
kubectl run subadd --rm -i --restart=Never -n free5gc --image=badouralix/curl-jq --env IMSI="$IMSI" --env PLMN="$PLMN" -- sh -c '
BASE=http://free5gc-webui:5000
TOKEN=$(curl -sfS -X POST "$BASE/api/login" -H "Content-Type: application/json" -d "{\"username\":\"admin\",\"password\":\"free5gc\"}" | jq -r ".token // .accessToken // .access_token")
curl -sS -o /dev/null -w "HTTP %{http_code}\n" -X DELETE "$BASE/api/subscriber/imsi-$IMSI/$PLMN" -H "Token: $TOKEN"
'
helm uninstall packetrusher2 -n free5gc 2>/dev/null || true
```
Deleting a subscriber that a registered UE is using forces that UE to deregister on its next periodic update.

## Known Issues

### All subscribers lost after a MongoDB restart
`free5gc-mongodb` uses `emptyDir`; a pod restart or reschedule wipes the database. Symptom: PacketRusher logs `Registration reject` and the AMF/AUSF log an authentication or `SUPI not found` error for an IMSI that used to work. Re-run the `subprov` Job (`free5gc-registration-unavailable.md`, Step 3c) rather than re-adding subscribers individually. Making MongoDB persistent is tracked as a follow-up.

### Keys must match byte-for-byte
K and OPc are hex strings compared exactly during 5G-AKA. A mismatch surfaces as `Authentication failure` / `MAC failure` in the AMF and AUSF logs without saying which key is wrong. Free5GC uses **OPc** (`opcValue`); leave `opValue` empty unless the UE is configured with OP instead.

### Slice and DNN must exist in the SMF and NSSF
The subscriber's slices (SST 1 / SD `010203`, `112233`) and DNNs must be present in `free5gc-smf-config` (`snssaiInfos`) and `free5gc-nssf-config`, otherwise PDU session establishment is rejected after a successful registration.

## Troubleshooting

| Issue | Check | Fix |
|-------|-------|-----|
| `curl: (7) Failed to connect` to the WebUI | `kubectl get svc free5gc-webui -n free5gc`, `kubectl get pods -n free5gc -l epc-mode=webui` | WebUI not Running; `kubectl rollout restart deploy free5gc-webui -n free5gc` |
| Login returns `401` | `helm get values free5gc -n free5gc -a` → `subprov.username` / `password` | Use the configured credentials |
| `POST` returns `500` with a MongoDB error | `kubectl logs -n free5gc deploy/free5gc-webui --tail=30` | MongoDB down or unreachable; fix via `free5gc-nf-unavailable.md`, never delete the Mongo pod |
| UE registers but gets no PDU session | SMF log: `snssai` / `dnn` not found | Align subscriber slice/DNN with `free5gc-smf-config` |
| UE gets `Registration reject` although the record exists | AMF/AUSF log: `Authentication failure` | K/OPc mismatch — compare hex values character by character with the UE config |
| Second PacketRusher stuck `ContainerCreating` | `kubectl describe pod -n free5gc -l app=packetrusher` → Multus IP conflict | Pick N2/N3 addresses not used by the first instance |

## Related SOPs
- **Previous:** `day1-deploy/deploy-free5gc-core.sop.md`
- **Next:** `day1-deploy/validate-free5gc-e2e.sop.md`
- **Restore all subscribers:** `day2-remediate/core/free5gc-registration-unavailable.md` (Step 3c)
