# Configure CPU Isolation and Performance Tuning

**Duration:** ~10 minutes
**Target:** Bare-metal worker nodes running DU/CU workloads

## Overview
Configure CPU governor, TuneD profile, and IRQ affinity for deterministic DU scheduling. Without these, kernel housekeeping tasks and frequency scaling cause latency spikes.

## Prerequisites
- SSH access to worker node
- RT kernel installed

## Steps

### Step 1: Set CPU governor to performance
```bash
ssh WORKER_NODE "echo performance | sudo tee /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor"
```
**Expected**: `performance` written to all CPUs

### Step 2: Install and activate TuneD
```bash
ssh WORKER_NODE "sudo apt-get install -y tuned && sudo tuned-adm profile latency-performance && sudo tuned-adm active"
```
**Expected**: `Current active profile: latency-performance`

### Step 3: Disable rp_filter on management interface
```bash
ssh WORKER_NODE "sudo sysctl -w net.ipv4.conf.all.rp_filter=0 && sudo sysctl -w net.ipv4.conf.default.rp_filter=0"
```
**Expected**: `net.ipv4.conf.all.rp_filter = 0`

### Step 4: Verify no frequency scaling
```bash
ssh WORKER_NODE "cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor"
```
**Expected**: `performance`

## Verification

### Final Check
```bash
ssh WORKER_NODE "tuned-adm active && cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor"
```
**Expected**: `latency-performance` and `performance`

## Related SOPs
- **Previous:** `day0-infra/configure-hugepages.md`
- **Next:** `day0-infra/configure-ptp.md`
