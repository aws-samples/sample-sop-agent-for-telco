# Remediate UPF PFCP Loss

**Duration:** ~5 minutes
**Severity:** critical
**Trigger:** `core_upf_pfcp_down` — SMF lost PFCP heartbeat to UPF

## Overview
The PFCP association between SMF and UPF has broken. No new PDU sessions can be established and existing sessions may timeout. The UPF runs on an edge node with hostNetwork, so this often indicates a network path issue or UPF crash.

## Prerequisites
- kubectl access to cluster
- SSM access to edge worker node running UPF

## Steps

### Step 1: Check UPF pod status
```bash
kubectl get pod -l app=open5gs-upf-host -n open5gs -o wide
```
**Expected**: UPF pod Running on edge node. If CrashLoopBackOff → Step 3.

### Step 2: Check SMF logs for PFCP errors
```bash
kubectl logs -l app.kubernetes.io/name=smf -n open5gs --tail=20 | grep -iE "PFCP|heartbeat|timeout"
```
**Expected**: `No Heartbeat` or `PFCP association failed` messages

### Step 3: Check UPF logs
```bash
kubectl logs -l app=open5gs-upf-host -n open5gs --tail=20 | grep -iE "PFCP|heartbeat|error"
```
**Expected**: Error messages indicating why PFCP broke

### Step 4: Verify ogstun interface exists on edge node
```bash
ssm_command INSTANCE_ID "ip addr show ogstun"
```
**Expected**: ogstun interface with IP 10.45.0.1/16. If missing → recreate it.

### Step 5: Recreate ogstun if missing
```bash
ssm_command INSTANCE_ID "sudo ip tuntap add name ogstun mode tun && sudo ip addr add 10.45.0.1/16 dev ogstun && sudo ip link set ogstun up"
```
**Expected**: No error output

### Step 6: Restart UPF pod
```bash
kubectl rollout restart deployment open5gs-upf-host -n open5gs
```
**Expected**: New UPF pod starts

### Step 7: Verify PFCP re-association
```bash
sleep 15
kubectl logs -l app.kubernetes.io/name=smf -n open5gs --tail=10 | grep "PFCP associated"
```
**Expected**: `PFCP associated [UPF_IP]:8805`

## Verification

### Final Check
```bash
kubectl logs -l app.kubernetes.io/name=smf -n open5gs | grep "PFCP associated" | tail -1
```
**Expected**: Recent PFCP association message

## Rollback
No destructive changes — remediation steps are additive (restart services, re-add routes).
If remediation worsens the situation, escalate to manual intervention.

## Troubleshooting

| Issue | Check | Fix |
|-------|-------|-----|
| UPF CrashLoopBackOff | ogstun missing on host | Recreate ogstun via SSM, then restart UPF |
| PFCP won't re-associate | SMF using wrong UPF address? | Verify SMF config has UPF hostNetwork IP, not service name |
| Network unreachable | EC2→Edge path broken? | Check VPN tunnel, route tables |
| UPF starts but no PFCP | Firewall blocking port 8805? | Check security groups, iptables on edge node |

## Related SOPs
- **Root cause:** `day2-remediate/infra/remediate-network-partition.md`
- **Deploy:** `day1-deploy/deploy-upf.md`
