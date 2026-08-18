# Add Subscriber to 5G Core

**Duration:** ~2 minutes
**Target:** MongoDB in Open5GS namespace

## Overview
Add a UE subscriber to the Open5GS MongoDB database with IMSI, authentication keys (K/OPC), and default APN/slice configuration. Required before any UE can register with the network.

## Prerequisites
- Open5GS core deployed with MongoDB running
- IMSI, K, and OPC values for the subscriber
- APN name matching the UE configuration

## Steps

### Step 1: Find MongoDB pod
```bash
MONGO_POD=$(kubectl get pods -n open5gs --no-headers | grep mongo | awk '{print $1}')
echo "MongoDB pod: $MONGO_POD"
```
**Expected**: Pod name (e.g., `mongodb-54b5bd8cfd-bmrk6`)

> **Note:** The MongoDB pod may not have standard labels. Use `grep mongo` rather than label selectors.

### Step 2: Add subscriber
```bash
kubectl exec $MONGO_POD -n open5gs -- mongosh open5gs --eval '
db.subscribers.deleteMany({"imsi":"IMSI_VALUE"});
db.subscribers.insertOne({
  "imsi": "IMSI_VALUE",
  "msisdn": [],
  "security": {
    "k": "K_VALUE",
    "amf": "8000",
    "op": null,
    "opc": "OPC_VALUE"
  },
  "ambr": {"downlink": {"value": 1, "unit": 3}, "uplink": {"value": 1, "unit": 3}},
  "slice": [{"sst": 1, "default_indicator": true,
    "session": [{"name": "APN_NAME", "type": 3,
      "ambr": {"downlink": {"value": 1, "unit": 3}, "uplink": {"value": 1, "unit": 3}},
      "qos": {"index": 9, "arp": {"priority_level": 8, "pre_emption_capability": 1, "pre_emption_vulnerability": 1}}
    }]
  }]
})'
```
**Expected**: `acknowledged: true, insertedId: ObjectId(...)`

> **Note:** The `deleteMany` before `insertOne` ensures idempotency — safe to run multiple times.

### Step 3: Verify subscriber exists
```bash
kubectl exec $MONGO_POD -n open5gs -- mongosh open5gs --eval 'db.subscribers.find({"imsi":"IMSI_VALUE"}, {"imsi":1, "security.k":1, "_id":0}).pretty()'
```
**Expected**: Document with matching IMSI and K value

## Verification

### Final Check
```bash
kubectl exec $MONGO_POD -n open5gs -- mongosh open5gs --eval 'db.subscribers.countDocuments({})'
```
**Expected**: Count ≥ 1

## Known Issues

### Subscribers lost on MongoDB restart
The default Gradiant Helm chart uses `emptyDir` for MongoDB storage. If the MongoDB pod restarts (node drain, OOM, etc.), **all subscribers are deleted**. You must re-add them.

**Detection:** UE gets `PLMN_NOT_ALLOWED` (NAS reject cause 11) after a MongoDB restart.

**Prevention:** Enable persistent volumes:
```bash
helm upgrade open5gs gradiant/open5gs -n open5gs --set mongodb.persistence.enabled=true --set mongodb.persistence.size=1Gi
```

### K and OPC must match UE config exactly
The K (subscriber key) and OPC (operator key) are hex strings. They must match the UE's USIM configuration byte-for-byte. A single character mismatch causes authentication failure — the AMF logs will show `Authentication failure` but won't tell you which key is wrong.

## Troubleshooting

| Issue | Check | Fix |
|-------|-------|-----|
| UE gets PLMN_NOT_ALLOWED | `db.subscribers.find({"imsi":"..."})` | Subscriber missing — re-add |
| UE gets auth failure | K/OPC match UE config? | Verify hex values character by character |
| mongosh not found | Image uses `mongo` shell? | Try `mongo` instead of `mongosh` |
| MongoDB pod not found by label | Labels differ per chart version | Use `grep mongo` on pod list |

## Related SOPs
- **Previous:** `day1-deploy/deploy-5g-core.md`
- **Next:** `day1-deploy/validate-e2e.md`
