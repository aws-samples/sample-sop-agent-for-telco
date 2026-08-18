# ANO Platform — Design Reference Guide

## For: Akshay, Sameer, Sivani, Awaiz
## Version: 1.1 | June 29, 2026
## Demo Target: July 28, 2026 (Docomo)

> **Note:** For architecture, runtime behavior, and how to run locally, see:
> - [`../README.md`](../README.md) — Architecture, project structure, quick start
> - [`runtime-architecture.md`](runtime-architecture.md) — Boot flow, config system, model resolver
> - [`provisioning-flow.md`](provisioning-flow.md) — ANPA bare-metal lifecycle
> - [`deployment-orchestration.md`](deployment-orchestration.md) — ANDA NF lifecycle + drain
>
> This document covers: **CRD schemas, team assignments, demo narrative, key decisions, and station data strategy.**

---

## 1. CRD Schemas

### PhysicalTopology (written by ANPA)

```yaml
apiVersion: topology.ano.aws.io/v1alpha1
kind: PhysicalTopology
metadata:
  name: site-002
  namespace: anra-system
spec:
  servers:
    - name: dell-worker-1
      bmc: 192.168.30.10
      role: edge
      cpu: { cores: 16, model: "Xeon E-2388G" }
      memory: 64Gi
      nics:
        - name: eth0
          mac: "aa:bb:cc:dd:ee:01"
          lldpPeer: leaf-switch-1/port-3
      rackPosition: { rack: "R1", unit: 12 }
    - name: dell-worker-2
      bmc: 192.168.30.11
      role: edge
      # ...
  switches:
    - name: leaf-switch-1
      ports: 48
      connections:
        - { port: 3, peer: dell-worker-1/eth0 }
        - { port: 4, peer: dell-worker-2/eth0 }
```

### ServiceTopology (written by ANDA)

```yaml
apiVersion: topology.ano.aws.io/v1alpha1
kind: ServiceTopology
metadata:
  name: site-002
  namespace: anra-system
spec:
  networkFunctions:
    - name: amf-1
      type: AMF
      namespace: open5gs
      host: ip-10-100-1-176
      connections:
        - { peer: gnb-du-01, protocol: NGAP, direction: inbound }
        - { peer: smf-1, protocol: SBI, direction: outbound }
        - { peer: nrf-1, protocol: SBI, direction: outbound }
    - name: smf-1
      type: SMF
      namespace: open5gs
      host: ip-10-100-2-8
      connections:
        - { peer: upf-1, protocol: PFCP, direction: outbound }
        - { peer: amf-1, protocol: SBI, direction: inbound }
    - name: upf-1
      type: UPF
      namespace: open5gs
      host: dell-worker-1
      connections:
        - { peer: smf-1, protocol: PFCP, direction: inbound }
        - { peer: gnb-du-01, protocol: GTP-U, direction: inbound }
    - name: gnb-du-01
      type: O-DU
      namespace: srsran
      host: dell-worker-2
      connections:
        - { peer: amf-1, protocol: NGAP, direction: outbound }
        - { peer: upf-1, protocol: GTP-U, direction: outbound }
  dataFlows:
    - name: user-plane
      path: [gnb-du-01, upf-1, internet]
      protocol: GTP-U
    - name: control-plane
      path: [gnb-du-01, amf-1, smf-1]
      protocol: NGAP/SBI
```

### ImpactMap (computed by Topology Controller)

```yaml
apiVersion: topology.ano.aws.io/v1alpha1
kind: ImpactMap
metadata:
  name: site-002
  namespace: anra-system
spec:
  lastReconciled: "2026-06-16T15:30:00Z"
  graphStats:
    nodes: 8
    edges: 12
    connectedComponents: 1
  singlePointsOfFailure:
    - node: amf-1
      reason: "Only AMF — all gNBs lose NGAP if it fails"
      affectedNFs: [gnb-du-01, smf-1, upf-1]
      estimatedUEs: 500
    - node: leaf-switch-1
      reason: "Single ToR switch for both edge servers"
      affectedNFs: [gnb-du-01, upf-1]
  nodeImpact:
    gnb-du-01:
      blastRadius: { nfs: 3, ues: 500, severity: Critical }
      cascadeChain: [gnb-du-01, amf-1, smf-1]
      hasFailover: false
      redundancy: { replicas: 1, minRequired: 1 }
    upf-1:
      blastRadius: { nfs: 2, ues: 500, severity: Critical }
      cascadeChain: [upf-1, smf-1]
      hasFailover: false
    amf-1:
      blastRadius: { nfs: 4, ues: 500, severity: Critical }
      cascadeChain: [amf-1, smf-1, gnb-du-01, upf-1]
      hasFailover: false
    nrf-1:
      blastRadius: { nfs: 6, ues: 500, severity: Critical }
      cascadeChain: [nrf-1, amf-1, smf-1, upf-1, gnb-du-01, ausf-1]
      hasFailover: false
```

---

## 2. How Each Person's Work Connects

### Sivani → Topology Controller

```
PhysicalTopology CRD ──┐
                       ├──► Topology Controller ──► ImpactMap CRD
ServiceTopology CRD ───┘         (your code)
```

Your controller is the **brain** that connects the physical world (hardware) to the service world (NFs). Without it, agents operate blind.

**Key interfaces:**
- INPUT: Watch `PhysicalTopology` + `ServiceTopology` CRDs
- OUTPUT: Write `ImpactMap` CRD
- CONSUMERS: ANRA (correlator.py), Dashboard (Akshay's visualization), ANDA (deployment safety)

### Sameer → Agent Configuration

```
agent-config.yaml ──► Config Loader ──► Agent Runtime
                                            │
                                            ├── Model: Haiku / Sonnet
                                            ├── Tools: [kubectl, ssm, redfish]
                                            ├── Approval: auto / human
                                            └── Thresholds: { ... }
```

Your config layer makes the platform **customizable without code changes**. A customer (like Docomo) provides their own agent-config.yaml + site-descriptor.yaml and gets a tailored autonomous system.

**Key interfaces:**
- INPUT: `agent-config.yaml` (mounted via ConfigMap)
- OUTPUT: Agent behavior changes (model, tools, approval mode)
- CONSUMERS: All 3 agents read config at startup + SOP templates reference thresholds

### Akshay → WebUI

```
┌─────────────────────────────────────────────┐
│                Dashboard                     │
│                                             │
│  ┌─────────────────────────────────────┐   │
│  │     Mission Control (3 agents)       │   │
│  └─────────────────────────────────────┘   │
│  ┌──────────────┐  ┌──────────────────┐   │
│  │  Topology    │  │  Alarm Detail    │   │
│  │  (ReactFlow) │  │  + Blast Radius  │   │
│  │              │  │                  │   │
│  │  ◉──◉──◉   │  │  🔴 500 UEs      │   │
│  │  │     │    │  │  affected         │   │
│  │  ◉──◉──◉   │  │  No failover     │   │
│  └──────────────┘  └──────────────────┘   │
└─────────────────────────────────────────────┘
```

Your UI is the **window** into the autonomous system. It shows Docomo that our agents are reasoning, detecting, and acting — all visible in real-time.

**Key interfaces:**
- INPUT: `/api/topology/impact` (ImpactMap data), `/api/agents/reasoning` (OODA feed)
- OUTPUT: Visual topology graph, blast radius panels, agent status cards
- DATA SOURCE: Backend reads ImpactMap CRD and serves it via REST

### Awaiz → Integration & Demo

```
Pipeline ──► Build ──► Deploy ──► All components running
                                       │
Demo Script ──► inject-alarm.sh ──► Full OODA loop visible
                                       │
                                       ▼
                            Docomo sees: "This is autonomous"
```

I'm the **glue** — making sure everyone's code works together, the pipeline deploys it all, and the demo tells a coherent story.

---

## 3. The Demo Story (July 28)

### What Docomo Sees

1. **Platform boots** → 3 agents come online, dashboard shows green
2. **Topology discovered** → ANPA finds hardware, ANDA maps NFs, controller computes ImpactMap
3. **Alarm fires** (DU CPU overload) → ANRA detects in <5s
4. **Blast radius computed** → "500 UEs affected, no failover, Critical"
5. **SOP selected** → topology-enriched: specific node, specific BMC, specific verification
6. **Auto-remediation** → CPU affinity fix applied via SSM
7. **Verified** → alarm clears, topology green again
8. **Config change** → operator swaps model/approval-mode → behavior changes instantly

### Key Message
> "You provide your site config and SOPs. We provide the autonomous reasoning engine that ties it all together."

---

## 4. Cross-Agent Communication

Agents coordinate through **two mechanisms**: direct function calls (fast, in-cluster)
and **CRD-mediated coordination** (declarative, auditable, GitOps-friendly).

### Direct Function Calls (synchronous queries)

```
ANRA (during alarm correlation):
  → ask_anpa_hardware_inventory("dell-worker-2")   # Is hardware healthy?
  → ask_anda_recent_deployments("open5gs")         # Did a deploy cause this?

ANDA (before deployment):
  → ask_anra_cluster_health()                      # Safe to deploy?
  → check ImpactMap: is target node a SPOF?        # Need drain first?

ANPA (during provisioning):
  → updates PhysicalTopology CRD                   # Triggers controller recompute
  → ask_anda_deployment_plan_status("...")         # Is deploy waiting on this node?
```

### CRD-Mediated Coordination (asynchronous handoffs)

For cross-agent **actions** (not just queries), agents communicate through CRDs:

```
ANRA detects alarm → decides redeploy needed:
  1. Creates DeploymentPlan CR (intent: deploy, triggeredBy: anra, priority: emergency)
  2. Calls POST /api/anda/wake (breaks ANDA's 30s poll sleep)

ANDA processes the CR:
  3. Reads DeploymentPlan CR (spec.intent, spec.priority, spec.networkFunctions)
  4. Classifies complexity → routes to FAST/SMART/EMERGENCY tier
  5. Executes deployment via SOP Bridge
  6. Patches CR status (phase: Completed, sopExecution: {...})

ANRA observes completion:
  7. Watches CR status (phase=Completed) → closes the incident
```

**Key principle:** CRDs are the inter-agent contract. Each agent owns its CRD writes;
others read + watch. No agent directly mutates another agent's CRDs.

### DeploymentPlan CRD Fields (Sprint 13)

| Field | Type | Purpose |
|-------|------|---------|
| `spec.intent` | `deploy│upgrade│remediation│scale│decommission│config-change` | Drives SOP selection + tier |
| `spec.priority` | `normal│high│emergency` | Emergency = Tier 3 (force) |
| `spec.triggeredBy` | `operator│anra│anpa│scheduled│gitops` | Audit trail |
| `spec.reason` | string | Human-readable context for AI |
| `spec.executionMode` | `live│replay│dry-run` | Controls real vs mock execution |
| `spec.networkFunctions[].vendor` | string | Vendor-specific SOP resolution |
| `spec.networkFunctions[].action` | string | Per-NF action override |
| `status.sopExecution` | map | Per-NF: tier used, SOP path, steps, duration |

---

## 5. Key Decisions (Don't Redo These)

| Decision | Rationale |
|----------|-----------|
| Topology Controller is NOT an agent | Deterministic graph math, no LLM needed, no Bedrock cost |
| Single-replica controller | Stateless recomputation, restart = full rebuild in <30s |
| CRD-based communication | Idiomatic K8s, declarative, watchable, auditable. CRDs are the inter-agent contract (no A2A/MCP needed) |
| ImpactMap is advisory, not authoritative | Eventually consistent; consumers assume max blast radius if stale |
| Agents are one image, three roles | Single Docker image, AGENT_ROLE env var selects behavior |
| Config-driven customization | No code changes for new sites/vendors/models |
| IRSA for Bedrock access | Pod-level IAM, no static credentials |
| Namespaces managed by kubectl, not Helm | Avoids ownership conflicts across releases |

---

## 6. Glossary

| Term | Meaning |
|------|---------|
| **OODA** | Observe → Orient → Decide → Act (agent reasoning loop) |
| **SOP** | Standard Operating Procedure (remediation playbook) |
| **NF** | Network Function (AMF, SMF, UPF, gNB, etc.) |
| **SPOF** | Single Point of Failure |
| **Blast Radius** | How many NFs/UEs are affected by a failure |
| **Cascade Chain** | Ordered list of NFs that fail if a given node fails |
| **NGAP** | Next Generation Application Protocol (gNB ↔ AMF) |
| **PFCP** | Packet Forwarding Control Protocol (SMF ↔ UPF) |
| **GTP-U** | GPRS Tunnelling Protocol - User plane (gNB ↔ UPF) |
| **SBI** | Service Based Interface (NRF, AMF, SMF inter-communication) |
| **Kopf** | Kubernetes Operator Pythonic Framework |
| **Strands** | Amazon's agent SDK for building LLM-powered agents |
| **IRSA** | IAM Roles for Service Accounts (pod-level AWS auth) |
| **CRD** | Custom Resource Definition (extends Kubernetes API) |
| **Redfish** | BMC management standard for bare-metal servers |

---

## 7. Station Data Generation Strategy

### Why This Sprint's Work Unlocks Station Data

Docomo's #1 priority is **Station Data Configuration** — auto-generating and validating the per-site parameters needed to deploy and operate a 5G network. This sprint builds the foundation:

```
┌─────────────────────────────────────────────────────────────────────┐
│              THIS SPRINT (Foundation)                                │
│                                                                     │
│  PhysicalTopology  +  ServiceTopology  +  ImpactMap                 │
│  (what hardware)      (what NFs)          (what depends on what)    │
└───────────────────────────────┬─────────────────────────────────────┘
                                │
                                │ enables
                                ▼
┌─────────────────────────────────────────────────────────────────────┐
│              NEXT PHASE (Station Data Generation)                    │
│                                                                     │
│  Site Descriptor  +  NF Catalog  +  Topology CRDs                   │
│       │                  │               │                          │
│       ▼                  ▼               ▼                          │
│  ┌──────────────────────────────────────────────────────┐           │
│  │         Station Data Generator (ANDA)                 │           │
│  │                                                      │           │
│  │  Inputs:                                             │           │
│  │  • Physical topology (servers, NICs, BMC)            │           │
│  │  • Service topology (NFs, protocols)                 │           │
│  │  • NF catalog (vendor, version, config schema)       │           │
│  │  • Site constraints (frequency, cell radius)         │           │
│  │                                                      │           │
│  │  Outputs:                                            │           │
│  │  • values.yaml per NF per site                       │           │
│  │  • Neighbor cell lists (auto-computed)               │           │
│  │  • PLMN / TAC / cell ID assignments                  │           │
│  │  • Validated station config package                  │           │
│  └──────────────────────────────────────────────────────┘           │
└─────────────────────────────────────────────────────────────────────┘
```

### The Station Data Generation Flow (Post This Sprint)

```
1. Operator provides:
   • site-descriptor.yaml (location, frequency, hardware)
   • nf-catalog.yaml (vendor NFs, config schemas)

2. ANPA discovers hardware → PhysicalTopology CRD
   • Servers, NICs, BMC addresses, rack positions
   • CPU/memory capabilities per node

3. ANDA generates station data:
   • Reads PhysicalTopology + site-descriptor + nf-catalog
   • AI-assisted: "given 2 edge servers with 16 cores each,
     place DU on server-1 (needs DPDK), CU on server-2"
   • Generates values.yaml per NF:
     - AMF: TAC, PLMN, NGAP bind address
     - gNB: cell ID, frequency, neighbor list, F1 addresses
     - UPF: GTP-U bind address, DNN config
   • Outputs validated config package

4. Topology Controller validates:
   • Builds graph from generated config
   • Checks: no SPOFs? all interfaces connected? redundancy met?
   • Flags issues BEFORE deployment

5. ANDA deploys with generated values:
   • helm install amf --values generated/amf-values.yaml
   • Updates ServiceTopology CRD
   • Controller recomputes ImpactMap

6. ANRA monitors:
   • Uses ImpactMap to assess blast radius of any issues
   • SOP templates reference actual station parameters
```

### What Docomo Gets

| Their Need | Our Answer |
|-----------|------------|
| "Auto-generate station config data" | PhysicalTopology + ServiceTopology + ANDA generator |
| "Validate station config before deploy" | ImpactMap (SPOF check, connectivity check) + Dashboard |
| "Generate instance parameters (values.yaml)" | ANDA + NF catalog + site-descriptor → per-NF Helm values |
| "AI Agent with high accurate outputs" | Strands Agent + topology context = grounded, not hallucinated |
| "Closed loop within management domain" | ANRA + ImpactMap = autonomous remediation with blast radius awareness |

### Key Insight

> **Without topology CRDs, station data generation is just glorified templating.**
> With topology CRDs, it's *intelligent* — the generator knows the physical constraints,
> the service dependencies, and can validate its own output before deployment.

---

## Links

- **Live Dashboard**: https://d1j3d0lbctd27j.cloudfront.net
