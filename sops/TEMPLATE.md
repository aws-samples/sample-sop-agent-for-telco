# SOP Title

**Duration:** ~X minutes
**Severity:** warning | critical
**Trigger:** alarm_name from alarm-references/*.json

## Overview
Brief description of what this SOP remediates and when it should be triggered.

## Prerequisites
- kubectl access to the cluster
- SSH access to worker node (if host-level remediation needed)
- Prior SOPs completed (if any)

## Steps

### Step 1: Diagnose
```bash
diagnostic command here
```
**Expected**: description of healthy vs unhealthy output

### Step 2: Remediate
```bash
remediation command here
```
**Expected**: expected result after fix

### Step 3: Verify
```bash
verification command here
```
**Expected**: confirmation that the issue is resolved

## Rollback
```bash
rollback command if remediation makes things worse
```

## Troubleshooting

| Issue | Check | Fix |
|-------|-------|-----|
| Problem description | Diagnostic command | Resolution steps |

## Related SOPs
- **Escalation:** link to next-level SOP if this doesn't resolve
- **Prevention:** link to config hardening SOP
