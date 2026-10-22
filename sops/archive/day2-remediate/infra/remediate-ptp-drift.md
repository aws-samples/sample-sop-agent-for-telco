# Remediate PTP Drift

**Duration:** ~5 minutes
**Severity:** critical
**Trigger:** PTP offset exceeding ±1.5µs, or `du_error_indication` with timing symptoms

## Overview
PTP synchronization has drifted beyond acceptable limits for 5G TDD operation. The DU requires sub-microsecond accuracy for slot boundaries. This SOP restores PTP synchronization.

## Prerequisites
- SSM access to edge worker node
- PTP grandmaster reachable on network

## Steps

### Step 1: Check current PTP offset
```bash
ssm_command MI_INSTANCE_ID "pmc -u -b 0 'GET CURRENT_DATA_SET' 2>/dev/null | grep offsetFromMaster || echo 'pmc not available'"
```
**Expected**: `offsetFromMaster` < 1000 (nanoseconds). If > 1500 → out of spec.

### Step 2: Check ptp4l process status
```bash
ssm_command MI_INSTANCE_ID "ps aux | grep ptp4l | grep -v grep"
```
**Expected**: ptp4l process running. If not → start it.

### Step 3: Check phc2sys status
```bash
ssm_command MI_INSTANCE_ID "ps aux | grep phc2sys | grep -v grep"
```
**Expected**: phc2sys running (syncs PTP hardware clock to system clock)

### Step 4: Restart ptp4l
```bash
ssm_command MI_INSTANCE_ID "sudo pkill -9 ptp4l; sleep 2; sudo ptp4l -i ens1f0 -m -2 -s > /tmp/ptp4l.log 2>&1 &"
```
**Expected**: ptp4l restarts

### Step 5: Restart phc2sys
```bash
ssm_command MI_INSTANCE_ID "sudo pkill -9 phc2sys; sleep 2; sudo phc2sys -s ens1f0 -c CLOCK_REALTIME -O 0 -m > /tmp/phc2sys.log 2>&1 &"
```
**Expected**: phc2sys restarts

### Step 6: Wait for convergence and verify
```bash
sleep 30
ssm_command MI_INSTANCE_ID "tail -5 /tmp/ptp4l.log"
```
**Expected**: Offset converging to < 100ns

## Verification

### Final Check
```bash
ssm_command MI_INSTANCE_ID "pmc -u -b 0 'GET CURRENT_DATA_SET' 2>/dev/null | grep offsetFromMaster"
```
**Expected**: `offsetFromMaster` < 1000

## Rollback
No destructive changes — remediation steps are additive (restart services, re-add routes).
If remediation worsens the situation, escalate to manual intervention.

## Troubleshooting

| Issue | Check | Fix |
|-------|-------|-----|
| ptp4l can't find grandmaster | Network L2 connectivity | Verify SFP link, check switch PTP config |
| No hardware timestamping | `ethtool -T ens1f0` | Load ice driver, update NIC firmware |
| Offset not converging | ptp4l log | Check grandmaster stability, try different PTP profile |
| phc2sys large offset | phc2sys log | Restart phc2sys after ptp4l has converged |

## Related SOPs
- **Setup:** `day0-infra/configure-ptp.md`
- **Downstream:** `day2-remediate/ran/remediate-du-timing-failure.md`
