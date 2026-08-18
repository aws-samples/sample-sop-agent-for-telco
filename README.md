# ANO Platform — Autonomous Network Operations

**One container image. Three AI agents. Full 5G network lifecycle automation.**

ANO is a Kubernetes-native platform that autonomously provisions, deploys, and operates 5G networks on AWS EKS Hybrid Nodes — from bare metal to running traffic.

```
  Day 0                Day 1                Day 2
┌─────────┐        ┌─────────┐        ┌─────────┐
│  ANPA   │──────► │  ANDA   │──────► │  ANRA   │
│Provision│        │ Deploy  │        │ Operate │
└─────────┘        └─────────┘        └─────────┘
     │                  │                   │
 Bare metal →      NFs running →      KPIs monitored →
 EKS nodes         in 3GPP order      auto-remediated
```

## Quick Start

```bash
# 1. Install dependencies
hatch env create

# 2. Run tests (710 tests, 60%+ coverage enforced)
hatch test

# 3. Run locally (defaults to ANRA role)
AGENT_ROLE=anra AGENT_CONFIG=configs/site-descriptors/sjc38.yaml hatch run dev

# 4. Deploy to cluster
helm install ano-platform helm-charts/ano-platform/ \
  --set image.repository=<ECR_URI> \
  --set image.tag=latest
```

## Architecture

### Single Image, Three Roles

The same container image runs as any of the three agents — selected by `AGENT_ROLE` env var:

| Agent | Role | What It Does | Runs On |
|-------|------|--------------|---------|
| **ANPA** | Day 0 Provisioning | Discovers BMC, installs OS via Tinkerbell, registers EKS nodes | Management cluster |
| **ANDA** | Day 1 Deployment | Deploys 5G NFs in 3GPP order, drains traffic for upgrades | Management cluster |
| **ANRA** | Day 2 Operations | Monitors KPIs, correlates alarms, auto-remediates via SOPs | Workload cluster |

### Runtime Architecture

Each pod runs **two concurrent processes**:

```
Pod Startup:
  main()
   ├── Validate config (schema + startup probes)
   ├── Start ConfigWatcher (hot-reload, no restart needed)
   ├── Background thread → agent's autonomous loop
   │     ├── ANRA: monitor alarms → correlate → SOP → remediate
   │     ├── ANDA: watch DeploymentPlan CRDs → deploy NFs
   │     └── ANPA: watch ProvisioningRequest CRDs → provision nodes
   └── Foreground: FastAPI on :8080 (health, REST API, WebUI)
```

If the background loop crashes → `os._exit(1)` → k8s restarts the pod.

### Key Subsystems

| System | Purpose | Details |
|--------|---------|---------|
| **Config Store** | Thread-safe config singleton | Any code calls `get_config()`, hot-reload updates it |
| **Config Watcher** | Detects ConfigMap changes | Polls mtime every 1s, debounces 2s, validates before swap |
| **Model Resolver** | Dynamic Bedrock model selection | `get_model("fast")` → Haiku, `get_model("smart")` → Sonnet |
| **Adaptive Steering** | Learns from past failures | Guides agent away from previously-failed approaches |
| **Site Descriptor** | Per-site config schema | One YAML per deployment site — drives all 3 agents |

## Project Structure

```
src/amzn_.../agent/
├── entrypoint.py          ← Boot: parse role, validate config, start threads
├── api.py                 ← FastAPI app factory (role-aware router registration)
├── config.py              ← SiteConfig schema + validation
├── monitor.py             ← ANRA alarm monitor loop
├── core/
│   ├── config_store.py    ← Thread-safe get_config() / set_config()
│   ├── config_watcher.py  ← File polling + hot-reload
│   └── model_resolver.py  ← Bedrock model tier resolution
├── agents/
│   ├── anra/              ← ANRA: correlator, SOP execution, tools
│   ├── anda/              ← ANDA: orchestrator, drain, config generator
│   │   ├── orchestrator.py    ← DeploymentPlan reconciler
│   │   ├── drain.py           ← AMF/PFCP/cell drain procedures
│   │   └── config_generator.py ← Helm values generation
│   └── anpa/              ← ANPA: reconciler, discovery, provisioning
│       └── reconciler.py      ← ProvisioningRequest state machine
├── routers/               ← FastAPI REST endpoints (per-feature)
└── adaptive_steering.py   ← Failure-pattern learning for agent guidance

helm-charts/
├── anra-common/           ← Shared CRDs (install first)
├── anpa/                  ← Day 0 agent chart
├── anda/                  ← Day 1 agent chart
├── anra/                  ← Day 2 agent chart (serves WebUI)
├── ano-platform/          ← Umbrella chart (all-in-one)
└── ano-topology/          ← Topology controller (kopf + networkx)

configs/
├── site-descriptors/      ← Per-site config (schema.yaml + examples)
├── influxdb/              ← Monitoring config
├── srsran/ & ueransim/    ← RAN simulator configs
└── nf-profiles/           ← 5G NF Helm value templates

sops/                      ← 25 Standard Operating Procedures
├── day0-infra/            ← Bootstrap, CPU isolation, hugepages, PTP
├── day1-deploy/           ← Core, RAN, UPF, monitoring deployment
└── day2-remediate/        ← Alarm-specific remediation playbooks
```

## Configuration

### Site Descriptor (the main config file)

Create one YAML per deployment site at `configs/site-descriptors/<site>.yaml`:

```yaml
site:
  name: ericsson-d15
  cluster: ericsson-d15
  region: us-west-2

aws:
  bedrockRoleArn: arn:aws:iam::794399553333:role/ERICSSON-3-JDA-Admin
  accountId: "794399553333"

hardware:
  nodes:
    - name: dell-xr8720t-01
      bmc_ip: 10.255.1.10
      oam_ip: 10.255.1.11
      roles: [worker, ran]
      mac: d0:37:45:39:94:5a
      bmc_type: idrac

images:
  registry: 794399553333.dkr.ecr.us-west-2.amazonaws.com

monitoring:
  influxdb_url: http://influxdb.monitoring:8086
  alertmanager_url: http://alertmanager.monitoring:9093
```

### Environment Variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `AGENT_ROLE` | `anra` | Agent persona: `anra`, `anda`, `anpa` |
| `PORT` | `8080` | HTTP server port |
| `LOG_LEVEL` | `info` | Logging verbosity |
| `AGENT_CONFIG` | — | Path to site descriptor YAML |
| `BEDROCK_MODEL_TIER` | `fast` | Default: `fast` (Haiku), `smart` (Sonnet) |
| `BEDROCK_MODEL_ID` | — | Override: use exact model ID |
| `BEDROCK_REGION` | `us-west-2` | AWS region for Bedrock API |

### Hot-Reload

Config changes are picked up automatically — no pod restart needed:
1. Update the ConfigMap (or mounted file)
2. ConfigWatcher detects mtime change within 1s
3. Debounces 2s (coalesces rapid K8s symlink swaps)
4. Validates new config; keeps old if invalid
5. Swaps config atomically + invalidates model cache

## Helm Deployment

### Install Order

```bash
# 1. CRDs first (always)
helm install anra-common helm-charts/anra-common/

# 2. Individual agents (or use ano-platform umbrella)
helm install anpa helm-charts/anpa/ --set image.repository=<ECR>
helm install anda helm-charts/anda/ --set image.repository=<ECR>
helm install anra helm-charts/anra/ --set image.repository=<ECR>

# OR: all-in-one
helm install ano helm-charts/ano-platform/ --set image.repository=<ECR>
```

### Credential Pattern

All agents use `existingSecret` — one Kubernetes Secret per site:
```yaml
existingSecret:
  name: site-credentials
  keys:
    bmcPassword: bmc-password
    sshKey: ssh-private-key
```

IRSA provides AWS credentials (Bedrock, SSM, ECR) — no static AWS keys.

## Development

```bash
# Build & test
hatch test                    # All tests (pytest)
hatch test -- -k "test_anpa" # Filter tests
hatch fmt                     # Format (ruff)
hatch run typing              # Type check (mypy)
hatch run release             # Full CI check (types + tests + coverage)

# Local dev server
hatch run dev                 # FastAPI on :8080

# Helm template testing
hatch test -- tests/helm/     # Helm chart unit tests
```

### Pipeline

- **Build system**: Hatch (via PeruHatch/Brazil)
- **CI**: Brazil Pipelines → CodeBuild (mirrors via CodeCommit)
- **Pre-push hook**: Auto-syncs to CodeCommit mirror (install with `pre-commit install --hook-type pre-push`)
- **Coverage**: 60% minimum enforced

## Technology Stack

| Layer | Tech |
|-------|------|
| **Agent Framework** | [Strands Agents SDK](https://github.com/strands-agents/sdk-python) + Amazon Bedrock (Claude) |
| **API** | FastAPI + Uvicorn |
| **Frontend** | React 18 + Ant Design + ReactFlow + Recharts |
| **Infrastructure** | Amazon EKS Hybrid Nodes (VPC + bare-metal) |
| **Provisioning** | Tinkerbell (DHCP/TFTP/iPXE) + Dell iDRAC VirtualMedia |
| **5G Core** | Open5GS (AMF, SMF, UPF, NRF) |
| **5G RAN** | srsRAN Project (gNB) + UERANSIM (testing) |
| **Monitoring** | InfluxDB + Telegraf + Alertmanager |
| **Packaging** | Helm 3 + ArgoCD |
| **CI/CD** | Brazil Pipelines + CodeBuild |

## Further Reading

- [`docs/ANO-Design-Reference-Guide.md`](docs/ANO-Design-Reference-Guide.md) — Architecture deep-dive, CRD schemas, team assignments
- [`docs/runtime-architecture.md`](docs/runtime-architecture.md) — Startup flow, config system, model resolution
- [`docs/provisioning-flow.md`](docs/provisioning-flow.md) — ANPA bare-metal provisioning end-to-end
- [`docs/deployment-orchestration.md`](docs/deployment-orchestration.md) — ANDA NF lifecycle + drain procedures
- [`DEVELOPING.md`](DEVELOPING.md) — Build system, git hooks, CodeCommit mirror
- [`CODE_QUALITY.md`](CODE_QUALITY.md) — Tech debt tracker + improvement roadmap
- [`SPRINT-PLAN.md`](SPRINT-PLAN.md) — Current sprint (July 28 Docomo demo)
