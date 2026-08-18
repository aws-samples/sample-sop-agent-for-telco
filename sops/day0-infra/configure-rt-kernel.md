# Configure Real-Time Kernel

**Duration:** ~15 minutes (+ reboot)
**Target:** Bare-metal worker nodes running DU/CU workloads

## Overview
Install and activate a PREEMPT_RT kernel for deterministic scheduling required by 5G DU MAC layer processing. Without RT kernel, DU scheduling latency is unpredictable and HARQ deadlines may be missed.

## Prerequisites
- SSH access to worker node
- Ubuntu 22.04 or 24.04
- Ubuntu Pro token (for linux-realtime kernel)

## Steps

### Step 1: Check current kernel
```bash
ssh WORKER_NODE "uname -r"
```
**Expected**: Non-RT kernel (e.g., `6.8.0-1015-aws`)

### Step 2: Enable Ubuntu Pro (if not already)
```bash
ssh WORKER_NODE "sudo pro attach TOKEN"
```
**Expected**: `This machine is now attached to an Ubuntu Pro subscription`

### Step 3: Enable realtime kernel
```bash
ssh WORKER_NODE "sudo pro enable realtime-kernel --assume-yes"
```
**Expected**: `Realtime kernel enabled`

### Step 4: Reboot
```bash
ssh WORKER_NODE "sudo reboot"
```
**Expected**: Node reboots (wait ~2 minutes)

### Step 5: Verify RT kernel
```bash
ssh WORKER_NODE "uname -r && uname -v | grep PREEMPT_RT"
```
**Expected**: Kernel version containing `realtime` and `PREEMPT_RT`

## Verification

### Final Check
```bash
ssh WORKER_NODE "cat /sys/kernel/realtime"
```
**Expected**: `1`

## Rollback
```bash
ssh WORKER_NODE "sudo pro disable realtime-kernel && sudo reboot"
```

## Related SOPs
- **Next:** `day0-infra/configure-hugepages.md`
- **Next:** `day0-infra/configure-cpu-isolation.md`
