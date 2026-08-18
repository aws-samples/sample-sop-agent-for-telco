# UPF Configuration SOP

**Stage:** 4 of 8  
**Status:** ✅ VALIDATED  
**Last Updated:** 2026-01-26  
**Duration:** ~3-5 minutes  
**Severity:** critical  
**Trigger:** upf_config_missing, gwu_not_activated

---

## Prerequisites
- UPF deployed via Helm
- All pods Running
- Health check passed (port 1024 LISTEN + ESTAB)

## Network Parameters
| Interface | VLAN | Logical IP | Physical IPs | BGP Peer |
|-----------|------|------------|--------------|----------|
| N3 | 3505 | 101.65.1.2/27 | 100.65.1.2/27, 100.65.1.34/27 | 100.65.1.1 |
| N4 | 3501 | 101.65.0.2/27 | 100.65.0.2/27, 100.65.0.34/27 | 100.65.0.1 |
| N6 | 3509 | 101.65.2.2/27 | 100.65.2.2/27, 100.65.2.34/27 | 100.65.2.1 |

**BGP:** Local AS 65100 → Remote AS 64764

## Steps

### 1. Set Management Pod
```bash
MGMT=$(kubectl get pod -n aws-upf -l app=upf-management-00 -o jsonpath='{.items[0].metadata.name}')
```

### 2. Health Check (gRPC)
```bash
kubectl exec -n aws-upf $MGMT -- ss -anp | grep :1024
```
**Expected:** One LISTEN and one ESTAB connection:
```
tcp   LISTEN    0      4096    100.77.4.71:1024    0.0.0.0:*
tcp   ESTAB     0      0       100.77.4.71:1024    100.77.4.184:37838
```

### 3. Create GWU
```bash
kubectl exec -n aws-upf $MGMT -- cre_gwu gwu01 lgwu001 shelf 0 blade 1
```

### 4. Configure N3
```bash
kubectl exec -n aws-upf $MGMT -- cre_gwuip lgwu001 ip_no 1 101.65.1.2/27 if_kind n3an vlan 3505
kubectl exec -n aws-upf $MGMT -- cre_gwuip gwu01 if_kind n3an vlan 3505 if1_addr 100.65.1.2/27 if2_addr 100.65.1.34/27
kubectl exec -n aws-upf $MGMT -- cre_gwurt interval 60
kubectl exec -n aws-upf $MGMT -- cre_gwurt gwu01 vlan 3505 own_as_no 65100 as_no_1 64764 ipv4_1 100.65.1.1 med_1 10 lpref_1 10
```

### 5. Configure N4
```bash
kubectl exec -n aws-upf $MGMT -- cre_gwuip lgwu001 ip_no 2 101.65.0.2/27 if_kind s5pgw vlan 3501
kubectl exec -n aws-upf $MGMT -- cre_gwuip gwu01 if_kind s5pgw vlan 3501 if1_addr 100.65.0.2/27 if2_addr 100.65.0.34/27
kubectl exec -n aws-upf $MGMT -- cre_gwurt gwu01 vlan 3501 own_as_no 65100 as_no_1 64764 ipv4_1 100.65.0.1 med_1 10 lpref_1 10
```

### 6. Configure N6
```bash
kubectl exec -n aws-upf $MGMT -- cre_apnp apn_id 1 apn APN1 type_pdn ipv4v6
kubectl exec -n aws-upf $MGMT -- cre_apnup apn_id 1 lgwu001 vlan_tag 3509 ipv4_nwadr_sgi 101.65.2.0/27 ipadr_sgi 101.65.2.2 nhop 101.65.2.1
kubectl exec -n aws-upf $MGMT -- cre_apnup apn_id 1 gwu01 vlan_tag 3509 if1_addr 100.65.2.2/27 if2_addr 100.65.2.34/27
kubectl exec -n aws-upf $MGMT -- cre_apnrt interval 60
kubectl exec -n aws-upf $MGMT -- cre_apnrt apn_id 1 gwu01 own_as_no 65100 as_no_1 64764 ipv4_1 100.65.2.1 med_1 10
```

### 7. Configure IP Pool and Unblock
```bash
kubectl exec -n aws-upf $MGMT -- cre_apnip apn_id 1 lgwu001 ipv4_pool 200.0.0.0/8 dyn_route on
kubectl exec -n aws-upf $MGMT -- ublk_apn apn_id 1
```

### 8. Activate UPF
```bash
kubectl exec -n aws-upf $MGMT -- ins_gwu lgwu001
```

---

## Verification

> **CRITICAL:** BGP convergence takes 90-120 seconds. All 3 neighbors establish sequentially (~30s apart). 
> **MUST wait 120 seconds after `ins_gwu` before checking status.**
> **MUST retry up to 3 times with 60-second intervals before reporting failure.**

### Wait for BGP Convergence
```bash
echo "Waiting 120 seconds for BGP convergence..."
sleep 120
```

### Check GWU Runtime Status
```bash
kubectl exec -n aws-upf $MGMT -- view_gwur
```
**Expected:** `sts=act`

> **IMPORTANT:** Use `view_gwur` (runtime), NOT `view_gwu st` (config). If `sts=ins`, wait 60 seconds and retry up to 3 times.

### Check BGP Neighbors
```bash
SVC=$(kubectl get pod -n aws-upf -l app=upf-service-01 -o jsonpath='{.items[0].metadata.name}')
kubectl exec -n aws-upf $SVC -- cat /var/log/platform/bgpd_128.log | grep "Up"
```
**Expected:** 3 lines showing neighbors Up:
```
neighbor 100.65.1.1 ... Up
neighbor 100.65.0.1 ... Up
neighbor 100.65.2.1 ... Up
```

> **NOTE:** BGP sessions establish sequentially. If fewer than 3 Up, wait 60 seconds and retry.

### Check Interfaces
```bash
kubectl exec -n aws-upf $SVC -- ip link show | grep -E "ethgrp|bnet"
```
**Expected:** 6 interfaces (ethgrp3505, ethgrp3501, ethgrp3509, bnet7010, bnet7011, bnet7002)

---

## Success Criteria
- GWU status: `act`
- 3 BGP sessions established
- 6 network interfaces created

## Rollback
If configuration causes service degradation, the operator MUST deactivate the GWU and remove the applied config:
```bash
MGMT=$(kubectl get pod -n aws-upf -l app=upf-management-00 -o jsonpath='{.items[0].metadata.name}')
kubectl exec -n aws-upf $MGMT -- blk_apn apn_id 1
kubectl exec -n aws-upf $MGMT -- del_gwu lgwu001
```
**Expected**: GWU returns to `oos` state; traffic stops routing through the reconfigured path. The operator SHOULD then re-apply the last known-good configuration.

## Troubleshooting

| Issue | Check | Fix |
|-------|-------|-----|
| GWU `sts=oos` | `view_gwur \| grep sts` | Wait 120s for BGP convergence, then retry `ins_gwu lgwu001` |
| GWU `sts=ini` | `view_gwur \| grep sts` | BGP still converging - wait 60s and recheck |
| BGP < 3 neighbors | `cat /var/log/platform/bgpd_128.log \| grep Up` | Wait 30s per neighbor (90s total), check network in `00-network-infra.md` |
| Interfaces missing | `ip link show \| grep ethgrp` | Check SR-IOV in `03-validation.md`, redeploy with `01-helm-deploy.md` |
| Pods not running | `kubectl get pods -n aws-upf` | Run `01-helm-deploy.md` |

## Related SOPs
- **01-helm-deploy.md** - Pod deployment issues
- **03-validation.md** - SR-IOV and infrastructure checks
- **05-load-test.md** - Next stage after UPF is ready

## UPF is Ready for Traffic

