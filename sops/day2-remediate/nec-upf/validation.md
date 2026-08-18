# UPF Validation SOP

**Stage:** 5 of 8  
**Status:** ✅ VALIDATED  
**Last Updated:** 2026-01-26  
**Duration:** ~2 minutes  
**Severity:** warning  
**Trigger:** upf_validation_required, post_deploy_check

---

## Purpose
Comprehensive health check for NEC UPF deployment.

## Prerequisites
- UPF MUST be deployed via Helm with all pods Running
- The operator MUST have kubectl access to the `aws-upf` namespace
- UPF configuration (upf-config.md) SHOULD be completed before validation

## Steps

### Quick Validation (All-in-One)
```bash
MGMT=$(kubectl get pod -n aws-upf -l app=upf-management-00 -o jsonpath='{.items[0].metadata.name}')
SVC=$(kubectl get pod -n aws-upf -l app=upf-service-01 -o jsonpath='{.items[0].metadata.name}')

echo "=== ArgoCD Sync ===" && kubectl get application nec-upf -n argocd -o jsonpath='{.status.sync.status} {.status.health.status}' 2>/dev/null || echo "ArgoCD not installed"
echo -e "\n=== Pods ===" && kubectl get pods -n aws-upf
echo -e "\n=== gRPC ===" && kubectl exec -n aws-upf $MGMT -- ss -anp 2>/dev/null | grep :1024
echo -e "\n=== GWU ===" && kubectl exec -n aws-upf $MGMT -- view_gwur 2>/dev/null
echo -e "\n=== BGP ===" && kubectl exec -n aws-upf $SVC -- vtysh -c "show bgp vrf all summary" 2>/dev/null | grep -E "100.65"
echo -e "\n=== BGP Routes ===" && kubectl exec -n aws-upf $SVC -- vtysh -c "show ip bgp vrf all" 2>/dev/null | grep -E "0.0.0.0/0|101.65"
echo -e "\n=== Interfaces ===" && kubectl exec -n aws-upf $SVC -- ip link show 2>/dev/null | grep -E "ethgrp|bnet" | wc -l
echo -e "\n=== CNI ===" && kubectl get pods -n kube-system | grep -E "multus|sriov"
echo -e "\n=== SR-IOV Resources ===" && kubectl get node -o json | jq -r '.items[].status.allocatable | to_entries[] | select(.key | startswith("intel.com")) | "\(.key): \(.value)"'
```

---

## Detailed Checks

### 0. ArgoCD Sync Status
```bash
kubectl get application nec-upf -n argocd -o jsonpath='Sync: {.status.sync.status}, Health: {.status.health.status}'
```
**Expected**: `Sync: Synced, Health: Healthy`

### 0b. ArgoCD Destination Namespace (Critical)
```bash
kubectl get application nec-upf -n argocd -o jsonpath='{.spec.destination.namespace}'
```
**Expected**: `aws-upf`

> **FAILURE if not `aws-upf`:** ArgoCD is deploying to the wrong namespace. All subsequent checks will fail. Fix immediately:
> ```bash
> kubectl -n argocd patch application nec-upf --type merge -p '{"spec":{"destination":{"namespace":"aws-upf"}}}'
> ```

### 0c. ArgoCD Git Connectivity
```bash
kubectl get application nec-upf -n argocd -o jsonpath='{.status.conditions}' | grep -c "ComparisonError"
```
**Expected**: `0` (no errors). If > 0, GitLab token may be expired — see SOP 03 Troubleshooting.

### 1. Pod Status
```bash
kubectl get pods -n aws-upf -o wide
```
**Expected**:
| Pod | Status | Restarts |
|-----|--------|----------|
| upf-management-00-xxx | Running | 0 |
| upf-rdb-xxx | Running | 0 |
| upf-service-01-xxx | Running | 0 |

### 2. gRPC Health Check
```bash
kubectl exec -n aws-upf $MGMT -- ss -anp | grep :1024
```
**Expected**:
- 1 LISTEN on port 1024
- 1+ ESTAB connections

### 3. GWU Status
```bash
kubectl exec -n aws-upf $MGMT -- view_gwur
```
**Expected**: `sts=act`

### 4. BGP Neighbors
```bash
kubectl exec -n aws-upf $SVC -- vtysh -c "show bgp vrf all summary" 2>/dev/null | grep -E "100.65|Neighbor"
```
**Expected**: 3 neighbors Up
- 100.65.1.1 (N3/vrfl1)
- 100.65.0.1 (N4/vrfl2)
- 100.65.2.1 (N6/vrfl3)

### 5. BGP Routes Received
```bash
kubectl exec -n aws-upf $SVC -- vtysh -c "show ip bgp vrf all" 2>/dev/null | grep -E "Network|0.0.0.0|101.65"
```
**Expected**: Each VRF should have:
- Default route (0.0.0.0/0) from peer
- Local loopback (101.65.x.2/32) advertised

### 6. Network Interfaces
```bash
kubectl exec -n aws-upf $SVC -- ip link show | grep -E "ethgrp|bnet"
```
**Expected**: 6+ interfaces
- ethgrp3505 (N3 logical)
- ethgrp3501 (N4 logical)
- ethgrp3509 (N6 logical)
- bnet7010, bnet7011 (N3 physical)
- bnet7002, bnet7003 (N4 physical)

### 6. CNI Stack
```bash
kubectl get pods -n kube-system | grep -E "multus|sriov"
```
**Expected**:
- kube-multus-ds-xxx: Running
- kube-sriov-device-plugin-xxx: Running

### 7. SR-IOV Resources
```bash
kubectl describe node | grep intel.com
```
**Expected**:
- intel.com/pci_sriov_net_datanet_a: 4
- intel.com/pci_sriov_net_datanet_b: 4

### 8. Events (Errors)
```bash
kubectl get events -n aws-upf --sort-by='.lastTimestamp' | grep -i error
```
**Expected**: No critical errors

---

## Success Criteria

| Check | Expected |
|-------|----------|
| ArgoCD | Synced, Healthy |
| ArgoCD namespace | `aws-upf` |
| ArgoCD git access | No ComparisonError |
| Pods | 3/3 Running, 0 restarts |
| gRPC | 1 LISTEN + 1+ ESTAB |
| GWU | sts=act |
| BGP | 3 neighbors Up |
| BGP Routes | Default route per VRF |
| Interfaces | 6+ created |
| Multus | Running |
| SR-IOV | Running, 4+4 VFs |

---

## Troubleshooting

**ArgoCD OutOfSync:**
```bash
kubectl patch application nec-upf -n argocd --type merge -p '{"operation":{"sync":{}}}'
```

**GWU not active:**
```bash
kubectl exec -n aws-upf $MGMT -- ins_gwu lgwu001
```

**BGP not established:**
```bash
kubectl exec -n aws-upf $SVC -- cat /var/log/platform/bgpd_128.log | tail -20
```

**Missing interfaces:**
- Verify `ins_gwu` completed
- Check SR-IOV VF allocation

**Pod CrashLoop:**
```bash
kubectl logs -n aws-upf <pod-name> --previous
kubectl describe pod -n aws-upf <pod-name>
```

## Rollback
Validation is read-only and requires no rollback. If validation reveals a failed deployment, the operator MUST follow the rollback in the relevant SOP (upf-config.md for config issues, nec-upf-deploy.md for deployment issues).
