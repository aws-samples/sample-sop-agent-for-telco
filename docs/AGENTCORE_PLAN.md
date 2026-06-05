# Plan: Bedrock AgentCore Deployment Option

> **Status:** Draft / Planning  
> **Last updated:** 2026-06-05  
> **AgentCore status:** GA (since Oct 2025)  
> **Owner:** [TBD]  
> **Target:** Add Amazon Bedrock AgentCore as a managed deployment alternative to the current self-hosted EKS pattern.

## Background

The current ANDA/ANRA deployment self-hosts the agent on Amazon EKS:

- Container image runs the Strands Agents SDK + FastAPI + monitor loop
- Agent identity via IRSA
- Tools (kubectl, SSH, AWS SSM, Redfish) implemented in-process
- Execution history stored in pod memory or Git issues
- Operator interaction via React UI on the pod

This plan explores using **Amazon Bedrock AgentCore** as a managed runtime for the same agent code, reducing operational overhead and unlocking AWS-managed features.

## What is Bedrock AgentCore? (Current state)

AgentCore is **GA as of October 2025** with consumption-based pricing and is composed of independent modular services:

| Service | What it gives us | Strands support |
|---------|------------------|-----------------|
| **Runtime** | Serverless agent hosting in isolated microVMs, **VPC connectivity GA**, sessions up to 8 hours, ZIP or container deployment | ✅ Native |
| **Harness** | Managed agent loop — define model + prompt + tools inline, single API call | ✅ |
| **Memory** | Short-term + long-term memory across sessions | ✅ Native |
| **Gateway** | Convert APIs/Lambda/MCP servers into MCP tools, **VPC egress via Lattice** | ✅ |
| **Identity** | Token-based identity (Cognito, Okta, Entra ID, Auth0) | ✅ |
| **Code Interpreter** | Sandboxed Python/JS/TS execution | ✅ |
| **Browser** | Cloud browser for vendor portals (Playwright/BrowserUse compatible) | ✅ |
| **Observability** | OpenTelemetry traces in CloudWatch | ✅ |
| **Evaluations** | Replaces our Strands Evals SDK usage; built-in agent evaluation | ✅ Native |
| **Policy** | **Cedar-based deterministic guardrails** — directly maps to our VoNR Safety Guard requirement | ✅ |
| **Registry** | Centralized catalog of agents/MCP servers/tools across the org | ✅ |
| **Payments** | x402 microtransactions for paid APIs (probably N/A for telco) | ✅ |

## Key Findings (from current docs)

### 1. VPC connectivity is GA — including Tokyo

AgentCore Runtime supports VPC connectivity in **ap-northeast-1** (Tokyo) and **us-west-2** (Oregon), our two relevant regions:

| Region | Code | Supported AZ IDs |
|--------|------|------------------|
| Tokyo | `ap-northeast-1` | `apne1-az1`, `apne1-az2`, `apne1-az4` |
| Oregon | `us-west-2` | `usw2-az1`, `usw2-az2`, `usw2-az3` |

The service creates ENIs in your VPC via service-linked role `AWSServiceRoleForBedrockAgentCoreNetwork`. Security groups control egress. **This eliminates the original concern about reaching private 5G NFs.**

⚠️ Caveat: Deleted ENIs may persist up to 8 hours in the customer VPC.

### 2. Sessions support long-running workloads

- `idleRuntimeSessionTimeout`: default **900s (15 min)**, configurable up to 28800s (8 hours)
- `maxLifetime`: default and max **28800s (8 hours)** — sessions get a new instance after that
- **Async tasks** (`add_async_task` / `complete_async_task`) keep sessions alive during long-running operations

For ANRA's 30s polling pattern: a session with `idleRuntimeSessionTimeout=3600` (1 hour) provides plenty of slack between polls. Or use **EventBridge to invoke a fresh session every 30s** — fits the consumption pricing model better.

### 3. Strands SDK is first-class

Direct code deployment recipe (from current docs):

```bash
uv init anra-agentcore --python 3.13
cd anra-agentcore
uv add bedrock-agentcore strands-agents
npm install -g @aws/agentcore
```

Agent entry point uses `@app.entrypoint` annotation from `bedrock-agentcore-sdk-python`. ZIP deployment is supported in addition to container — better for fast iteration cycles.

### 4. AgentCore Policy = our Safety Guard requirement

The Policy service intercepts every tool call before execution using **Cedar policy language** (open-source AWS policy language). This is exactly what we need for VoNR commercial deployments:

```cedar
// Block destructive SCP operations during active emergency calls
forbid(
  principal,
  action == ToolCall::"kubectl_delete_pod",
  resource is K8sResource
) when {
  resource.namespace == "5gc" &&
  resource.name like "scp-*" &&
  context.active_emergency_calls > 0
};
```

This eliminates building our own pre-execution gate.

### 5. AgentCore Evaluations replaces Strands Evals usage

We currently use `strands-agents-evals` directly. AgentCore Evaluations is built on Strands Evals SDK + OpenTelemetry, with results integrated into AgentCore Observability/CloudWatch. Migration is straightforward.

### 6. MCP servers can be hosted in Runtime

Our existing kubectl/SSM/Redfish tool implementations can be deployed as **separate MCP servers** in AgentCore Runtime, then made available via Gateway. This decouples tool execution from the main agent and supports independent scaling.

## Why Migrate?

### Pros (with current information)

1. **No infrastructure to operate.** Drop EKS pods, services, IRSA roles, container images.
2. **Built-in everything.** Memory, Identity, Observability, Evaluations all managed.
3. **VPC connectivity GA.** Reaches our private 5G NFs, EKS clusters, InfluxDB without changes.
4. **Strands native.** Same agent code, just different deployment.
5. **Cedar Policy** for VoNR Safety Guard requirement (huge for commercial deployment).
6. **8-hour sessions + async tasks** handle our 30s polling and long-running remediations.
7. **Tokyo region GA** — works for KubeCon Japan / DOCOMO/NEC commercial path.
8. **Registry** discoverability across multi-tenant operator scenarios.

### Cons / Trade-offs

1. **AWS lock-in.** Current EKS deployment is portable to any K8s; AgentCore is AWS-only. Acceptable for AWS-native customers; problematic for telcos requiring multi-cloud.
2. **Pricing model.** Consumption-based — need to model 24/7 polling cost vs steady-state EKS pod. Quick math: 30s polls × 86,400 s/day = 2,880 invocations/day. Need actual unit pricing from `aws.amazon.com/bedrock/agentcore/pricing/`.
3. **Container constraints.** ARM64 required for AgentCore Runtime containers. Current image is x86_64 → needs multi-arch build.
4. **15-minute tool execution cap.** Long Helm install + cluster bootstrap operations need to use async tasks pattern.
5. **8-hour session limit.** Sessions get a new microVM after 8 hours — agent state must be in Memory service, not in-memory.
6. **ENI cleanup latency.** ENIs in customer VPC persist up to 8 hours after deletion; affects rapid iteration cycles.

## Proposed Architecture

```
┌────────────────────────────────────────────────────────────────┐
│  Customer VPC (ap-northeast-1)                                  │
│                                                                 │
│  ┌──────────┐  ┌──────────┐  ┌──────────────┐                  │
│  │ srsRAN   │  │ Open5GS  │  │ Dell iDRAC   │                  │
│  │ gNB      │  │ NFs      │  │ BMC          │                  │
│  └────┬─────┘  └────┬─────┘  └────┬─────────┘                  │
│       │             │             │                             │
│       └── Telegraf ──────┐  ┌─────┘                             │
│                          ▼  ▼                                   │
│                     ┌──────────┐                                │
│                     │ InfluxDB │                                │
│                     └────┬─────┘                                │
│                          │                                      │
│                          │ AgentCore ENI                        │
│                          │ (in private subnet)                  │
│                          ▼                                      │
│  ┌──────────────────────────────────────────────────┐           │
│  │  AgentCore Runtime (microVM)                      │           │
│  │   ┌────────────────────────────────┐             │           │
│  │   │ ANRA Agent (Strands)           │             │           │
│  │   │  @app.entrypoint               │             │           │
│  │   │   - sop_executor.py            │             │           │
│  │   │   - sop_graph.py               │             │           │
│  │   │   - correlator.py              │             │           │
│  │   └────────────────────────────────┘             │           │
│  └─────┬────────────────────────────────────────────┘           │
│        │                                                        │
│        ▼                                                        │
│  ┌────────────────┐    ┌──────────────────┐                     │
│  │ AgentCore      │    │ AgentCore        │                     │
│  │ Memory         │    │ Gateway          │                     │
│  │ (exec history) │    │  ↓ MCP tools     │                     │
│  └────────────────┘    │ - kubectl-mcp    │                     │
│                        │ - ssm-mcp        │                     │
│  ┌────────────────┐    │ - redfish-mcp    │                     │
│  │ AgentCore      │    │ - influxdb-mcp   │                     │
│  │ Policy (Cedar) │    └──────────────────┘                     │
│  │  Safety Guard  │                                             │
│  └────────────────┘                                             │
└────────────────────────────────────────────────────────────────┘
                          │
                          │ Bedrock InvokeModel
                          ▼
                   ┌──────────────────┐
                   │ Amazon Bedrock   │
                   │ Claude tier      │
                   └──────────────────┘

  ┌────────────────────────────────────────────┐
  │  EventBridge (every 30s) ─→ AgentCore       │
  │  invoke for monitor cycle                   │
  └────────────────────────────────────────────┘

  ┌────────────────────────────────────────────┐
  │  API Gateway ─→ AgentCore                   │
  │  for operator-initiated invocations         │
  │  + inbound Redfish webhooks                 │
  └────────────────────────────────────────────┘
```

## Migration Phases

### Phase 0: Discovery and cost modeling (1 week)

- [ ] Get unit pricing for AgentCore Runtime, Memory, Gateway, Policy in target regions (us-west-2, ap-northeast-1) → compute monthly cost for 30s polling pattern + bursty user-initiated remediations
- [ ] Compare to current EKS cost (~$73/mo control plane + ~$70/mo for 1 node = ~$143/mo per cluster)
- [ ] Stand up hello-world Strands agent on AgentCore Runtime in us-west-2
- [ ] Measure cold start latency (must fit <30s detection-to-action SLA)
- [ ] Validate VPC connectivity with a private RDS/ElastiCache endpoint
- [ ] Confirm Tokyo region availability for production deployment

### Phase 1: Proof of Concept (2 weeks)

- [ ] Convert agent entry point to use `@app.entrypoint` annotation
- [ ] Use `uv` + `bedrock-agentcore-sdk-python` for project structure
- [ ] Deploy via direct ZIP deployment to Runtime
- [ ] Wire one SOP end-to-end (e.g., `remediate-nf-crashloop`)
- [ ] Use AgentCore Memory for execution history (replaces in-pod storage)
- [ ] Use AgentCore Identity instead of IRSA
- [ ] Use AgentCore Observability instead of custom logging

### Phase 2: Tool migration via Gateway (2 weeks)

- [ ] Wrap kubectl as MCP server in AgentCore Runtime → register as Gateway target
- [ ] Wrap AWS SSM as MCP server (or use Lambda target)
- [ ] Wrap Redfish BMC as MCP server
- [ ] Wrap InfluxDB query as MCP server
- [ ] Replace in-process `agent/sop_executor.py` tool implementations with Gateway calls
- [ ] Configure Gateway VPC egress via VPC Lattice for private services

### Phase 3: Policy + Evaluations (1 week)

- [ ] Author Cedar policies for production guardrails (e.g., never restart all SCP pods at once, never act during emergency calls)
- [ ] Wire AgentCore Policy as pre-execution gate
- [ ] Migrate evaluation logic from `evals/evaluators.py` to AgentCore Evaluations
- [ ] Verify pass/fail signals flow correctly into Observability dashboards

### Phase 4: Scheduling and triggers (1 week)

- [ ] EventBridge rule on 30s schedule → invoke ANRA for monitor cycle
- [ ] API Gateway → AgentCore Runtime for inbound Redfish webhook events
- [ ] Direct invocation API for operator-initiated remediations (replaces "Ask ANRA" chat)

### Phase 5: UI and operator experience (1 week)

- [ ] Replace in-pod React UI with static UI (S3 + CloudFront) calling AgentCore via API Gateway
- [ ] Migrate dashboard widgets (alarms, SOPs, topology, chat)
- [ ] Or: deploy UI as an AG-UI server in AgentCore Runtime (newer pattern)

### Phase 6: Validation (1 week)

- [ ] Run all 6 workshop SOPs against AgentCore deployment
- [ ] Verify Day 2 closed-loop: detection → remediation latency <60s SLA
- [ ] Verify cost matches Phase 0 projection
- [ ] Side-by-side comparison: EKS vs AgentCore deployment metrics

### Phase 7: Documentation and release (1 week)

- [ ] Document AgentCore deployment in `docs/DEPLOYMENT_AGENTCORE.md`
- [ ] Add deployment chooser to README (`helm` / `agentcore`)
- [ ] Optional: add AgentCore lab to workshop (post-event)
- [ ] Publish to AgentCore Registry for org-wide discoverability

## Decision Points

These need answers before committing to AgentCore as the primary deployment:

1. **Cost ceiling.** Is consumption-based pricing actually cheaper than $143/mo per EKS cluster for our 30s poll cadence? Phase 0 must answer this with real pricing.
2. **Multi-cloud requirement.** Some telco customers require Azure/GCP portability. AgentCore is AWS-only. Do we need to maintain both EKS (portable) and AgentCore (managed) forever?
3. **Cold start budget.** The Day 2 remediation SLA is <60s. Cold start latency must be measured and fit within this.
4. **Operator UX.** AgentCore Runtime is request-driven. The current "always-on dashboard with WebSocket updates" UX needs adaptation.
5. **Customer perception.** "Run on AWS-managed agent runtime" vs "deploy our own agent" — which positions better with operators evaluating AI for network ops?

## Recommendation (post-Phase-0)

**Maintain both deployment patterns.**

| Use case | Recommended deployment |
|----------|------------------------|
| AWS-native customer, greenfield | AgentCore — minimal ops, built-in everything |
| Hybrid / on-prem / multi-cloud | EKS — portable, customer-controlled |
| Workshop / learning | EKS — visible internals, easier to inspect |
| Production VoNR with safety requirements | AgentCore — Cedar Policy is the killer feature here |
| Multi-operator catalog | AgentCore Registry |

Both should converge on the same agent code surface (the `agent/` directory). The runtime layer is what differs.

## Migration mapping

| Current (EKS) | AgentCore equivalent |
|---------------|----------------------|
| `Dockerfile` + `docker-entrypoint.sh` | `bedrock-agentcore-sdk-python` `@app.entrypoint` + ARM64 multi-arch build |
| IRSA pod identity | AgentCore Identity (Cognito/Okta/Entra/Auth0) |
| In-pod execution history | AgentCore Memory (short-term + long-term) |
| `agent/sop_executor.py` tool implementations | MCP servers behind AgentCore Gateway |
| Custom safety logic in Python | AgentCore Policy with Cedar |
| `evals/` directory | AgentCore Evaluations (uses Strands Evals under the hood) |
| Custom logging to CloudWatch | AgentCore Observability (OpenTelemetry → CloudWatch) |
| Manual `helm install` | `agentcore deploy` CLI command |
| Webhook server on port 8081 | API Gateway → AgentCore |
| 30s polling loop in monitor | EventBridge schedule → AgentCore invoke |

## References (current as of June 2026)

- [What is Amazon Bedrock AgentCore?](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/what-is-bedrock-agentcore.html) — service overview + pricing
- [Configure AgentCore Runtime for VPC](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/agentcore-vpc.html) — VPC connectivity (GA, includes Tokyo)
- [Direct code deployment for Python](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-get-started-code-deploy-python.html) — Strands deployment recipe
- [Lifecycle settings](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-lifecycle-settings.html) — session timeouts (up to 8 hours)
- [Long-running agents](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-long-run.html) — async task pattern
- [Deploy MCP servers in AgentCore Runtime](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-mcp.html) — for kubectl/SSM/Redfish wrappers
- [AgentCore Gateway core concepts](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway-core-concepts.html)
- [AgentCore Gateway VPC egress](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway-vpc-egress.html) — for accessing private services
- [Security best practices](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-security-best-practices.html)
- [Strands Agents SDK](https://strandsagents.com/) — framework documentation
- [bedrock-agentcore-sdk-python](https://github.com/aws/bedrock-agentcore-sdk-python) — Python SDK
- [AgentCore CLI](https://www.npmjs.com/package/@aws/agentcore) — `npm install -g @aws/agentcore`

## Next Action

1. **Create discovery spike branch** (`dev/agentcore-spike`) and stand up hello-world Strands agent on AgentCore Runtime
2. **Get pricing data** for the consumption units relevant to our pattern (sessions/sec, GB-hours of memory, gateway invocations)
3. **Build cost projection** for both 30s polling and on-demand remediation models
4. **Test VPC connectivity** to a private InfluxDB endpoint to validate the architecture
5. **Schedule design review** with the team after Phase 0 results
