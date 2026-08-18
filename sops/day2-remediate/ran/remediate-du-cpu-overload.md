# Remediate DU CPU Overload

**Duration:** ~5 minutes
**Severity:** critical
**Trigger:** `du_cpu_overload` — DU MAC CPU usage exceeds 70%

## Overview
The DU's MAC scheduler is experiencing CPU contention, causing increased scheduling latency, late HARQ responses, and throughput degradation. This SOP identifies the cause and restores normal DU operation.

## Prerequisites
- kubectl access to the RAN namespace
- SSH access to the worker node running the DU pod

## Steps

### Step 1: Confirm DU CPU is elevated
```bash
kubectl exec -n ran $(kubectl get pod -n ran -l app=du -o jsonpath='{.items[0].metadata.name}') -- top -bn1 | head -15
```
**Expected**: DU process showing high CPU usage

### Step 2: Identify competing processes on the host
```bash
kubectl get pod -n ran -l app=du -o jsonpath='{.items[0].spec.nodeName}' | xargs -I{} ssh {} "ps aux --sort=-%cpu | head -10"
```
**Expected**: List of top CPU consumers — look for non-DU processes on isolated cores

### Step 3: Check CPU affinity and isolation
```bash
kubectl get pod -n ran -l app=du -o jsonpath='{.items[0].spec.nodeName}' | xargs -I{} ssh {} "cat /proc/cmdline | tr ' ' '\n' | grep isolcpus"
```
**Expected**: `isolcpus=X-Y` showing cores reserved for DU

### Step 4: Kill competing processes (if found)
```bash
kubectl get pod -n ran -l app=du -o jsonpath='{.items[0].spec.nodeName}' | xargs -I{} ssh {} "kill -9 <competing_pid>"
```
**Expected**: Competing process terminated

### Step 5: Verify DU latency recovered
```bash
kubectl exec -n ran $(kubectl get pod -n ran -l app=du -o jsonpath='{.items[0].metadata.name}') -- cat /proc/self/status | grep voluntary_ctxt_switches
```
**Expected**: Context switches stabilized, DU latency back to normal (<500µs)

## Rollback
```bash
kubectl rollout restart deployment/du -n ran
```

## Troubleshooting

| Issue | Check | Fix |
|-------|-------|-----|
| No isolcpus configured | `cat /proc/cmdline` | Add `isolcpus=2-7` to kernel boot params |
| DU not using isolated cores | `taskset -cp <du_pid>` | Set CPU affinity: `taskset -cp 2-7 <du_pid>` |
| IRQ affinity wrong | `cat /proc/interrupts` | Use `irqbalance --banirq` or set SMP affinity |

## Related SOPs
- **Escalation:** If CPU overload persists after clearing competing processes, escalate to capacity planning
- **Prevention:** `infra/configure-cpu-isolation.md`
