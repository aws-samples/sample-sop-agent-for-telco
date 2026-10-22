# Remediate OS Memory Pressure

**Duration:** ~5 minutes
**Severity:** warning
**Trigger:** memory_pressure, hugepage_exhaustion, high_swap_usage from alarm-references/os-linux.yaml

## Overview
Remediates Linux memory pressure on worker nodes that host 5G NFs. Memory pressure causes latency spikes and OOM kills that disrupt DU scheduling and UPF packet processing.

## Prerequisites
- SSM access to the affected worker node
- kubectl access to the cluster

## Steps

### Step 1: Diagnose memory state
```bash
ssm_command --instance-id {{ssm_id}} --command "free -h && cat /proc/pressure/memory && cat /proc/meminfo | grep -E 'Huge|Swap|MemAvail'"
```
**Expected**: Shows available memory, PSI stall time, hugepage and swap state

### Step 2: Identify top memory consumers
```bash
ssm_command --instance-id {{ssm_id}} --command "ps aux --sort=-%mem | head -15"
```
**Expected**: Shows processes sorted by memory usage — look for unexpected consumers

### Step 3: Check pod resource usage
```bash
kubectl top pods -A --sort-by=memory | head -20
```
**Expected**: Shows pod memory usage — identify pods exceeding limits

### Step 4: Clear page cache if pressure is from cache
```bash
ssm_command --instance-id {{ssm_id}} --command "sync && echo 3 > /proc/sys/vm/drop_caches"
```
**Expected**: Frees cached memory without affecting running processes

### Step 5: Restart memory-leaking pods if identified
```bash
kubectl delete pod {{pod_name}} -n {{namespace}}
```
**Expected**: Pod restarts with fresh memory allocation

### Step 6: Verify pressure resolved
```bash
ssm_command --instance-id {{ssm_id}} --command "cat /proc/pressure/memory && free -h"
```
**Expected**: PSI stall time stops increasing, available memory recovered

## Rollback
```bash
# No destructive changes — cache drop and pod restart are safe operations
# If a pod was deleted, Kubernetes recreates it automatically
```

## Troubleshooting

| Issue | Check | Fix |
|-------|-------|-----|
| Hugepages exhausted | `cat /proc/meminfo \| grep Huge` | Reserve at boot: `hugepagesz=1G hugepages=16` in kernel cmdline |
| Swap thrashing | `vmstat 1 5` — check si/so columns | Disable swap: `swapoff -a` (required for RT workloads) |
| OOM kills recurring | `dmesg \| grep -i oom` | Set pod memory limits in deployment spec |

## Related SOPs
- **Escalation:** remediate-network-partition.md (if memory pressure causes NF crashes)
- **Prevention:** configure-hugepages.md (Day 0 hugepage reservation)
