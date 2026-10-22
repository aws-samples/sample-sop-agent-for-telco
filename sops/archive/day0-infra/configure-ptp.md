# Configure PTP Timing Synchronization

**Duration:** ~10 minutes
**Target:** Bare-metal worker nodes with Intel E810 NICs

## Overview
Configure PTP (Precision Time Protocol) for 5G TDD synchronization. The DU requires sub-microsecond timing accuracy for TDD slot boundaries. Uses hardware timestamping on Intel E810 NICs.

## Prerequisites
- SSH access to worker node
- Intel E810 NIC with SFP+ connected to PTP grandmaster
- linuxptp package

## Steps

### Step 1: Install linuxptp
```bash
ssh WORKER_NODE "sudo apt-get install -y linuxptp"
```
**Expected**: `linuxptp` installed

### Step 2: Identify PTP-capable interface
```bash
ssh WORKER_NODE "ethtool -T ens1f0 2>/dev/null | grep -i 'hardware-transmit\|hardware-receive\|hardware-raw-clock'"
```
**Expected**: All three capabilities listed (hardware timestamping supported)

### Step 3: Start ptp4l
```bash
ssh WORKER_NODE "sudo ptp4l -i ens1f0 -m -2 -s &"
```
**Expected**: `ptp4l` starts, begins synchronizing with grandmaster

### Step 4: Start phc2sys (sync system clock to PTP)
```bash
ssh WORKER_NODE "sudo phc2sys -s ens1f0 -c CLOCK_REALTIME -O 0 -m &"
```
**Expected**: `phc2sys` starts, offset converging to <100ns

## Verification

### Final Check
```bash
ssh WORKER_NODE "pmc -u -b 0 'GET CURRENT_DATA_SET' 2>/dev/null | grep offsetFromMaster"
```
**Expected**: `offsetFromMaster` < 1000 (nanoseconds)

## Troubleshooting

| Issue | Check | Fix |
|-------|-------|-----|
| No hardware timestamping | `ethtool -T <iface>` | Update NIC firmware, load ice driver |
| Large offset (>1µs) | `ptp4l` logs | Check grandmaster, verify SFP link |
| phc2sys not converging | `phc2sys` logs | Restart phc2sys, check PTP domain |

## Related SOPs
- **Previous:** `day0-infra/configure-cpu-isolation.md`
- **Remediation:** `day2-remediate/infra/remediate-ptp-drift.md`
