# Remediate Network Partition

**Duration:** ~10 minutes
**Severity:** critical
**Trigger:** `core_amf_gnb_down` + `core_scp_timeout` — multiple core alarms indicating connectivity loss

## Overview
Network partition between AWS region (EC2 nodes) and on-prem edge (Dell workers). The RAN is isolated from the core network. All UEs lose service. Common causes: VPN tunnel down, routing change, Unifi gateway issue.

## Prerequisites
- kubectl access to cluster
- SSM access to edge worker nodes
- AWS CLI access for VPN tunnel status

## Steps

### Step 1: Confirm partition — check node status
```bash
kubectl get nodes -o wide
```
**Expected**: Edge nodes (mi-*) showing NotReady or with stale heartbeat

### Step 2: Check VPN tunnel status
```bash
aws ec2 describe-vpn-connections --filters "Name=state,Values=available" --query 'VpnConnections[].VgwTelemetry[].{Status:Status,OutsideIP:OutsideIpAddress,StatusMessage:StatusMessage}' --region us-west-1 --output table
```
**Expected**: Both tunnels showing `UP`. If `DOWN` → VPN issue.

### Step 3: Test connectivity from EC2 to edge node
```bash
kubectl run nettest --rm -it --restart=Never --image=busybox --overrides='{"spec":{"nodeSelector":{"role":"region"}}}' -- ping -c 3 -W 3 192.168.31.222
```
**Expected**: Ping replies. If 100% loss → transport path broken.

### Step 4: Check edge node reachability via SSM
```bash
ssm_command mi-026bd2d584e205efb "ip route show && echo '---' && ping -c 2 -W 3 10.100.1.1"
```
**Expected**: Routes present, ping to VPC succeeds. If SSM works but ping fails → routing issue.

### Step 5: Check Unifi gateway (if applicable)
```bash
ssm_command mi-026bd2d584e205efb "ip route show | grep -E 'default|10.100|10.0'"
```
**Expected**: Default route via Unifi gateway, routes to VPC CIDRs

### Step 6: If VPN tunnel is down, wait for auto-recovery
```bash
echo "VPN tunnels auto-negotiate. Wait 60 seconds..."
sleep 60
aws ec2 describe-vpn-connections --filters "Name=state,Values=available" --query 'VpnConnections[].VgwTelemetry[].Status' --region us-west-1 --output text
```
**Expected**: `UP UP` after recovery

### Step 7: Verify core NFs can reach edge after recovery
```bash
kubectl logs -l app.kubernetes.io/name=smf -n open5gs --tail=5 | grep "PFCP"
kubectl logs -l app.kubernetes.io/name=amf -n open5gs --tail=5 | grep "gNB"
```
**Expected**: PFCP re-association and gNB reconnection messages

## Verification

### Final Check
```bash
kubectl get nodes | grep -E "mi-" | awk '{print $1, $2}'
```
**Expected**: All edge nodes `Ready`

## Rollback
No destructive changes — remediation steps are additive (restart services, re-add routes).
If remediation worsens the situation, escalate to manual intervention.

## Troubleshooting

| Issue | Check | Fix |
|-------|-------|-----|
| VPN tunnel DOWN | AWS VPN console | Check Unifi gateway IPsec config, restart tunnel |
| Routes missing on edge | `ip route show` via SSM | Re-add routes: `ip route add 10.100.0.0/16 via GATEWAY` |
| Unifi gateway rebooted | Check gateway uptime | Routes may need re-adding after gateway reboot |
| TGW route missing | AWS TGW route table | Add static route for edge CIDR to VPN attachment |
| Edge nodes NotReady | kubelet can't reach API server | Restart kubelet: `systemctl restart kubelet` |

## Related SOPs
- **Downstream:** `day2-remediate/core/remediate-amf-gnb-disconnect.md`
- **Downstream:** `day2-remediate/core/remediate-upf-pfcp-loss.md`
