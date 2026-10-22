# SOP 09: Outpost Infrastructure Health Check

**Duration:** ~3 minutes
**Severity:** warning
**Trigger:** outpost_capacity_degraded, dedicated_host_unavailable

## Overview
Verify AWS Outpost SJC38 infrastructure health including dedicated hosts, capacity, and instance status. The operator MUST run this check before any provisioning or deployment that depends on Outpost capacity.

## Key Words (RFC 2119)
The key words "MUST", "MUST NOT", "SHOULD", "SHOULD NOT", and "MAY" in this document are to be interpreted as described in [RFC 2119](https://www.rfc-editor.org/rfc/rfc2119).

## Prerequisites
- AWS credentials with Outpost read access MUST be configured
- The `telcocli` tool MUST be available
- Network connectivity to the AWS Outpost control plane MUST be established

**IMPORTANT**: The operator MUST use the `telcocli` tool for EVERY step below. The operator MUST NOT use run_command.

## Steps

### Step 1: List Outposts
The operator MUST list all Outposts and confirm SJC38 is ACTIVE.

```bash
telcocli list-outposts --output table
```
**Expected**: Outpost `aws-5gc-kinara-01-outpost-SJC38-4306` status is `ACTIVE` with 1 host available.

### Step 2: Describe Outpost Details
The operator MUST get detailed capacity and host information.

```bash
telcocli describe-outpost --outpost-id op-0bd76a1afdfdcb9db --include-capacity --include-hosts --output table
```
**Expected**:
- Instance types include `bmn-cx2.metal-48xl` (192 vCPU)
- Lifecycle status is `ACTIVE`

### Step 3: Analyze Dedicated Hosts
The operator MUST check dedicated host allocation and utilization.

```bash
telcocli analyze-dedicated-hosts
```
**Expected**: Host `h-0b06c84c876314a63` is `available`, instance type `bmn-cx2.metal-48xl`.

### Step 4: Outpost Utilization Summary
The operator MUST get overall utilization across all Outposts.

```bash
telcocli get-outpost-utilization-summary
```
**Expected**: At least 1 running instance on SJC38.

### Step 5: System Health Check
The operator MUST run a health check and verify connectivity.

```bash
telcocli health
```
**Expected**: Status is `HEALTHY`, all systems operational.

## Rollback
This SOP is read-only — it performs no mutations and requires no rollback. If checks fail, the operator MUST escalate to AWS Outpost support rather than attempting remediation.

## Troubleshooting

| Issue | Check | Fix |
|-------|-------|-----|
| Outpost not ACTIVE | `telcocli list-outposts` | Check AWS console, verify network connectivity to Outpost |
| No dedicated hosts | `telcocli analyze-dedicated-hosts` | Verify host allocation in EC2 console |
| Health check fails | `telcocli health` | Check AWS credentials and network connectivity |

## Related SOPs
- **Escalation:** AWS Outpost support if infrastructure is degraded
- **Next:** validation.md — verify UPF workload health once infrastructure is confirmed
