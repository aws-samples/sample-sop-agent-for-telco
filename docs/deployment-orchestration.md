# Deployment Orchestration — ANDA NF Lifecycle

> How ANO deploys, upgrades, and drains 5G network functions with zero dropped calls.

## Overview

ANDA watches `DeploymentPlan` custom resources and orchestrates the full NF lifecycle:

```
DeploymentPlan CR (spec.nfs: [{name: amf, version: 2.1.0}, ...])
        │
        ▼
┌──────────────────────────────────────────────────────────────────────┐
│  ANDA Orchestrator                                                    │
│                                                                       │
│  For each NF (in 3GPP dependency order):                              │
│                                                                       │
│    preflight ──► drain ──► deploy ──► wait_rollout ──► postdeploy    │
│                                                                       │
│  Plan Status: InProgress → Completed | PartiallyFailed | Failed       │
└──────────────────────────────────────────────────────────────────────┘
```

## 3GPP Deployment Order

NFs are sorted by dependency before processing (can't deploy AMF before NRF):

```
nrf → udr → udm → ausf → nssf → pcf → smf → upf → amf → af
```

NFs not in this list are appended at the end (custom/vendor NFs).

## Orchestrator Startup

```
run_orchestrator()
  ├── _check_and_bootstrap_infrastructure()   ← one-time
  │     ├── Check missing platform components (ArgoCD, cert-manager, etc.)
  │     ├── Sort by wave number (dependency order)
  │     └── Deploy missing via Helm/kubectl (non-blocking on failure)
  │
  └── while True:   ← every 30s
        _poll_once()
          ├── List DeploymentPlan CRDs (phase = Pending or empty)
          └── For each: process_deployment_plan(plan)
```

## Per-NF Deployment Pipeline

### Step 1: Preflight Check

Validates the target cluster is ready:
- Namespace exists
- Required CRDs present
- Sufficient node capacity
- No existing deployment in degraded state

### Step 2: Upgrade Strategy Lookup

Each NF has a configurable upgrade strategy (`configs/nf-profiles/`):

```yaml
# upgrade-strategy.yaml
- nf_name: amf
  strategy: rolling
  drain_required: true
  max_unavailable: 0
  health_check_timeout: 120

- nf_name: upf
  strategy: blue-green
  drain_required: true
  pfcp_redirect: true
```

### Step 3: Traffic Drain (if required)

**The critical part** — ANDA drains active sessions before touching a running NF.

#### AMF Drain (`drain_amf_sessions`)

```
1. Find AMF pod in namespace
2. Scrape amf_registered_ue_count metric
3. If > 0:
   a. Signal AMF to reject new registrations (PATCH config)
   b. Wait for existing UEs to re-register to other AMFs
   c. Poll metric every 5s until count = 0 (timeout: 120s)
4. Verify: scrape again, confirm 0
```

#### PFCP Redirect (`redirect_pfcp_traffic`)

For UPF upgrades — redirects user-plane traffic:

```
1. Find SMF pod (PFCP controller)
2. Identify PFCP sessions on target UPF
3. Trigger PFCP Session Modification (redirect to backup UPF)
4. Wait for GTP tunnel count on target UPF → 0
5. Verify no active data sessions remain
```

#### Cell Bar/Unbar (RAN upgrades)

```
bar_cell()
  └── Signal gNB to bar the cell → UEs trigger handover to adjacent cells

trigger_handover()
  └── Force remaining UEs to handover (for stubborn devices)

[... deploy upgrade ...]

unbar_cell()
  └── Re-enable cell → UEs can attach again
```

#### Session Count Verification

Before proceeding, ANDA verifies drain is complete:

| Check Function | What It Verifies |
|---------------|-----------------|
| `check_active_sessions(nf_type)` | AMF/SMF registration count = 0 |
| `check_gtp_tunnel_count()` | UPF GTP-U tunnels = 0 |
| `check_ue_count()` | RAN connected UEs = 0 |

### Step 4: Deploy

Two deployment methods:

#### Helm Deploy (`_deploy_nf_helm`)
```python
helm upgrade --install <nf_name> <chart> \
  --namespace <ns> \
  --version <version> \
  --values <generated_values> \
  --wait --timeout 300s
```

#### ArgoCD Deploy (`_deploy_nf_argocd`)
```python
# Sync the ArgoCD Application
argocd app sync <nf_name> --timeout 300
# Wait for health
argocd app wait <nf_name> --health --timeout 300
```

### Step 5: Wait for Rollout

```bash
kubectl rollout status deployment/<nf_name> -n <ns> --timeout=600s
```

Timeout: 10 minutes (configurable). If exceeded → `RolloutTimeout` status.

### Step 6: Post-Deploy Validation

- Pod health check (all replicas Running + Ready)
- Service endpoint reachable
- NF-specific health (e.g., AMF registers with NRF, UPF PFCP association)

## Plan Status Tracking

### Overall Plan Status

| Status | Meaning |
|--------|---------|
| `InProgress` | Currently deploying NFs |
| `Completed` | All NFs deployed + verified |
| `PartiallyFailed` | Some NFs succeeded, some failed |
| `Failed` | All NFs failed or critical dependency failed |

### Per-NF Status

Stored in `status.nfStatuses.<nf_name>`:

| Status | Meaning |
|--------|---------|
| `Deployed` | Successfully deployed + rollout complete |
| `PreflightFailed` | Cluster not ready |
| `DrainFailed` | Could not drain sessions (timeout) |
| `DeployFailed` | Helm/ArgoCD deploy failed |
| `RolloutTimeout` | Pods didn't become Ready in 10min |
| `PostDeployFailed` | NF unhealthy after deploy |

## Config Generation

ANDA can generate Helm values dynamically using `config_generator.py`:

```python
# Tools available to the AI agent:
read_helm_values(chart_path)         # Read current values.yaml
describe_node(node_name)             # kubectl describe node
kubectl_query(args)                  # Arbitrary kubectl
helm_dry_run(chart, values_yaml)     # Validate before deploy
save_generated_values(yaml, name)    # Persist for deploy
```

## DeploymentPlan CRD Example

```yaml
apiVersion: deployment.anda.aws.io/v1alpha1
kind: DeploymentPlan
metadata:
  name: deploy-core-v2
  namespace: anda-system
spec:
  site: docomo-site-002
  cluster: site-002-workload
  intent: deploy                    # deploy | upgrade | remediation | scale | decommission | config-change
  reason: "Scheduled 5G core deployment for site-002"
  triggeredBy: operator             # operator | anra | anpa | scheduled | gitops
  priority: normal                  # normal | high | emergency
  executionMode: live               # live | replay | dry-run
  networkFunctions:
    - name: nrf
      type: open5gs
      namespace: open5gs
      action: deploy
      vendor: open5gs
    - name: amf
      type: open5gs
      namespace: open5gs
      action: deploy
      vendor: open5gs
    - name: smf
      type: open5gs
      namespace: open5gs
      action: deploy
      vendor: open5gs
    - name: upf
      type: open5gs
      namespace: open5gs
      action: deploy
      vendor: open5gs
status:
  phase: Completed
  message: "All 4 NFs deployed successfully"
  nfStatuses:
    nrf: Deployed
    amf: Deployed
    smf: Deployed
    upf: Deployed
  sopExecution:
    nrf:
      tier: 1
      phase: Deployed
      duration: "3.8s"
    amf:
      tier: 2
      phase: Deployed
      sopUsed: "sops/day1-deploy/deploy-5g-core.md"
      stepsExecuted: 8
      duration: "42s"
    smf:
      tier: 2
      phase: Deployed
      sopUsed: "sops/day1-deploy/deploy-5g-core.md"
      stepsExecuted: 6
      duration: "38s"
    upf:
      tier: 2
      phase: Deployed
      sopUsed: "sops/day1-deploy/deploy-upf.md"
      stepsExecuted: 10
      duration: "65s"
```

## ServiceTopology Emission

After successful deployment, ANDA emits a `ServiceTopology` CR:

```yaml
apiVersion: topology.telco.amazon.com/v1alpha1
kind: ServiceTopology
metadata:
  name: core-topology
spec:
  nodes:
    - name: amf
      type: network-function
      namespace: core
      protocol: NAS/NGAP
    - name: smf
      type: network-function
      namespace: core
      protocol: PFCP
    - name: upf
      type: network-function
      namespace: core
      protocol: GTP-U
  edges:
    - from: amf
      to: smf
      protocol: SBI
    - from: smf
      to: upf
      protocol: PFCP/N4
```

This feeds the Topology Controller → ImpactMap → ANRA blast radius correlation.

## Adaptive Steering

ANDA uses `AdaptiveSteeringHandler` to learn from past failures:

```
Before each tool call:
  1. Load failure patterns from last 5 runs (logs/*.jsonl)
  2. Extract target (namespace, NF name) from tool input
  3. If same tool + target failed before:
     → Inject guidance: "Previous attempt failed with: <error>. Try alternative."
  4. Agent adjusts approach based on guidance
```

This prevents the agent from repeating the same failed kubectl/helm commands.

## SOP Bridge — Intelligent Execution Routing

> Added Sprint 13. See `agents/anda/sop_bridge.py`.

The SOP Bridge sits between the orchestrator (which watches CRs) and the SOP executor
(which runs AI agents). It classifies complexity, selects SOPs, merges tool sets,
and provides automatic fallback to direct Helm when AI is unavailable.

### 3-Tier Execution Model

```
                    ┌─────────────────────────────────────────┐
                    │         Complexity Classifier            │
                    │  classify_complexity(nf, intent, strat)  │
                    └────────────┬────────────────────────────┘
                                 │
              ┌──────────────────┼──────────────────┐
              ▼                  ▼                  ▼
     ┌────────────────┐ ┌────────────────┐ ┌────────────────┐
     │   TIER 1: FAST │ │  TIER 2: SMART │ │ TIER 3: EMERG  │
     │  Direct Helm   │ │   SOP + AI     │ │ Force + Audit  │
     │  No AI, <5s    │ │  30-120s       │ │   <10s         │
     └────────────────┘ └────────────────┘ └────────────────┘
```

| Tier | When | How | Cost |
|------|------|-----|------|
| **FAST** (1) | Stateless NFs (nrf, udr, udm) + `intent: deploy` + no drain | `helm upgrade --install` directly | Zero AI cost, <5s |
| **SMART** (2) | Stateful NFs OR drain required OR `intent: remediation` OR retry | Full SOP executor with AI reasoning | Bedrock call, 30-120s |
| **EMERGENCY** (3) | `priority: emergency` | `helm upgrade --force` first, audit CR after | Zero AI cost, <10s |

### Complexity Classifier

```python
def classify_complexity(nf_name, intent, strategy, priority) -> int:
    if priority == "emergency":          return TIER_EMERGENCY
    if intent == "remediation":          return TIER_SMART
    if strategy.has_drain_steps():       return TIER_SMART
    if nf in stateless_set and deploy:   return TIER_FAST
    return TIER_SMART  # default: safe
```

Stateless NFs: `nrf`, `udr`, `udm`, `monitoring`  
Complex actions triggering Tier 2: `drain`, `signal-amf-deregistration`, `pfcp-session-redirect`, `cell-barring`, `trigger-handover`

### SOP Resolver

The resolver maps `(intent, nf_category, vendor)` → SOP file path:

```python
SOP_REGISTRY = {
    ("deploy", "core", "*"):      "sops/day1-deploy/deploy-5g-core.md",
    ("deploy", "upf", "open5gs"): "sops/day1-deploy/deploy-upf.md",
    ("deploy", "upf", "nec"):     "sops/day1-deploy/nec-upf-deploy.md",
    ("deploy", "ran", "*"):       "sops/day1-deploy/deploy-ran-du.md",
    ("remediation", "*", "*"):    "sops/day2-remediate/{nf_type}.md",
    ("decommission", "*", "*"):   "sops/day2-decommission.md",
}
```

Resolution priority: exact match → wildcard vendor → wildcard category.  
ConfigMap override: `/etc/anda/sop-mapping/sop-registry.yaml` (operators can add custom SOPs without code changes).  
Fallback: If no SOP matches → Tier 1 (direct helm). Never blocks on a missing SOP.

### Feature Flag

```bash
SOP_BRIDGE_ENABLED=true   # default: enabled
SOP_BRIDGE_ENABLED=false  # bypass all bridge logic, use legacy direct-helm path
```

Set via env var or ConfigMap. When disabled, orchestrator skips bridge dispatch entirely.

### AI Failure Modes

| Failure | Detection | Response |
|---------|-----------|----------|
| Bedrock down | `BedrockUnavailableError` (or legacy `SystemExit(1)`) | Fall back to Tier 1 (direct helm) |
| AI hallucination | SteeringHooks blocks dangerous commands | Tool call cancelled, agent retries |
| Tool budget exhausted | `_before_tool_call` cancels at step 95 | Agent forced to summarize |
| Partial success (3/5) | Bridge checks output for ❌ markers | If `rollbackOnFailure=true`, auto-rollback |
| Agent timeout | `threading.Event.wait(timeout)` | Kill thread, mark `TimedOut` |

### Progress Tracking (`progress_hook.py`)

Two-layer progress reporting:

1. **In-memory** (`app_state.push_activity("anda", ...)`) — every tool call, real-time via `GET /api/agents/reasoning`
2. **CR patches** — only on phase transitions (max 5 per plan):
   - `Pending → Validating → InProgress → Completed/Failed`
   - Batched with 10s throttle; terminal phases bypass throttle

```python
# Example CR status after execution
status:
  phase: Completed
  sopExecution:
    nrf:
      tier: 1
      phase: Deployed
      duration: 4.2s
    amf:
      tier: 2
      phase: Deployed
      sopUsed: sops/day1-deploy/deploy-5g-core.md
      stepsExecuted: 8
      duration: 45s
```

### Wake Endpoint (Urgent Trigger)

```
POST /api/anda/wake
```

Sets `threading.Event` to break the 30s poll sleep immediately.  
Used by ANRA's cross-agent tool when creating an emergency DeploymentPlan CR.  
Result: emergency remediation in <1s instead of waiting up to 30s.


## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| Plan stuck InProgress | NF rollout hanging | Check pod events: `kubectl describe pod -n <ns>` |
| DrainFailed | AMF won't release UEs | Check if UEs have alternative AMF; may need manual deregister |
| DeployFailed (Helm) | Values mismatch | Check generated values vs chart expectations |
| DeployFailed (ArgoCD) | Sync conflict | Check ArgoCD UI for diff; may need `argocd app sync --force` |
| PostDeployFailed | NF can't register with NRF | Check NRF is healthy first; verify SBI URLs in config |
