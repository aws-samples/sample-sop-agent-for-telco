# Remediate DU Timing Failure

**Duration:** ~5 minutes
**Severity:** critical
**Trigger:** `du_error_indication` — DU reporting error indications, likely timing-related

## Overview
The DU is reporting error indications and late HARQ responses, typically caused by PTP timing drift or loss of synchronization. In TDD mode, timing accuracy below ±1.5µs is required for correct slot boundaries.

## Prerequisites
- kubectl access to cluster
- SSM access to edge worker node running gNB

## Steps

### Step 1: Check gNB error indicators
```bash
kubectl logs srsran-gnb -n srsran --tail=20 | grep -iE "error|late|timing|sync"
```
**Expected**: Error indication or late HARQ messages

### Step 2: Check PTP daemon status on DU node
```bash
ssm_command MI_INSTANCE_ID "systemctl status ptp4l 2>/dev/null || ps aux | grep ptp4l"
```
**Expected**: ptp4l running. If not → restart it.

### Step 3: Check PTP offset
```bash
ssm_command MI_INSTANCE_ID "journalctl -u ptp4l --no-pager -n 10 2>/dev/null || echo 'ptp4l not running as service'"
```
**Expected**: Offset values < 1000ns. If > 1500ns → timing is out of spec.

### Step 4: Check NIC hardware timestamping
```bash
ssm_command MI_INSTANCE_ID "ethtool -T ens1f0 2>/dev/null | grep -i hardware || echo 'No HW timestamping'"
```
**Expected**: Hardware timestamping capabilities listed

### Step 5: Restart PTP daemon if not running or offset too high
```bash
ssm_command MI_INSTANCE_ID "sudo pkill ptp4l; sleep 2; sudo ptp4l -i ens1f0 -m -2 -s &"
```
**Expected**: ptp4l restarts and begins synchronizing

### Step 6: Restart gNB to clear error state
```bash
kubectl delete pod srsran-gnb -n srsran
sleep 15
kubectl logs srsran-gnb -n srsran --tail=10 | grep -iE "cell|started|error"
```
**Expected**: Cell started without errors

## Verification

### Final Check
```bash
kubectl logs srsran-gnb -n srsran --tail=5 | grep -c "error_indication"
```
**Expected**: `0` errors

## Rollback
No destructive changes — remediation steps are additive (restart services, re-add routes).
If remediation worsens the situation, escalate to manual intervention.

## Troubleshooting

| Issue | Check | Fix |
|-------|-------|-----|
| ptp4l not installed | `which ptp4l` | `apt install linuxptp` |
| No HW timestamping | `ethtool -T` | Update NIC firmware, load ice driver |
| Large offset (>1µs) | ptp4l logs | Check grandmaster, verify SFP link |
| No grandmaster | Network topology | Verify PTP grandmaster is reachable on L2 |

## Related SOPs
- **Infra:** `day0-infra/configure-ptp.md`
- **Root cause:** `day2-remediate/infra/remediate-ptp-drift.md`
