# Configure Hugepages

**Duration:** ~5 minutes
**Target:** Bare-metal worker nodes running DU/CU/UPF workloads

## Overview
Allocate 2MB hugepages for DPDK and DU shared memory. Required for high-performance packet processing in UPF and low-latency memory access in DU.

## Prerequisites
- SSH access to worker node
- RT kernel installed (see `day0-infra/configure-rt-kernel.md`)

## Steps

### Step 1: Check current hugepage allocation
```bash
ssh WORKER_NODE "grep -i huge /proc/meminfo"
```
**Expected**: `HugePages_Total: 0` (not yet configured)

### Step 2: Allocate hugepages (2GB = 1024 x 2MB)
```bash
ssh WORKER_NODE "echo 1024 | sudo tee /sys/kernel/mm/hugepages/hugepages-2048kB/nr_hugepages"
```
**Expected**: `1024`

### Step 3: Make persistent across reboots
```bash
ssh WORKER_NODE "echo 'vm.nr_hugepages=1024' | sudo tee -a /etc/sysctl.d/99-hugepages.conf && sudo sysctl -p /etc/sysctl.d/99-hugepages.conf"
```
**Expected**: `vm.nr_hugepages = 1024`

### Step 4: Mount hugetlbfs (if not already)
```bash
ssh WORKER_NODE "sudo mkdir -p /dev/hugepages && sudo mount -t hugetlbfs nodev /dev/hugepages 2>/dev/null; echo 'ok'"
```
**Expected**: `ok`

## Verification

### Final Check
```bash
ssh WORKER_NODE "grep -i huge /proc/meminfo | head -4"
```
**Expected**: `HugePages_Total: 1024`, `HugePages_Free: 1024`

## Related SOPs
- **Previous:** `day0-infra/configure-rt-kernel.md`
- **Next:** `day0-infra/configure-cpu-isolation.md`
