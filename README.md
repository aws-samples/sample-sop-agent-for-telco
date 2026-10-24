# Workshop v3 — Free5GC Autonomous Network Operations

**CloudFormation infrastructure. Free5GC data plane. ANDA and ANRA operations. No ANPA deployment.**

Workshop-v3 is based on `origin/workshop-v2` commit `e938040` and replaces its attendee infrastructure path with the validated IND321 CloudFormation, Multus, gtp5g, Free5GC, PacketRusher, and Prometheus assets. CloudFormation owns Day 0; ANDA and ANRA provide deployment and operations. The ANPA implementation remains in the source tree for compatibility but is disabled by default and is not installed by the workshop-v3 scripts.

```text
CloudFormation → EKS/Multus/gtp5g → Free5GC/PacketRusher
                                      │
                                      ▼
                     Prometheus/Alertmanager/Grafana
                                      │
                                      ▼
                                  ANDA + ANRA
```

See [`docs/workshop-v3.md`](docs/workshop-v3.md) for the pinned version/IP contracts, security boundaries, and known limitations.

## Quick Start

```bash
# Development validation (no AWS resources created)
hatch env create
hatch test
make workshop-v3-validate

# Full disposable-account bring-up
export STACK_NAME=telco-dryrun-01
export AWS_DEFAULT_REGION=us-west-2
export BASTION_KEY=<existing-key-pair>
export AGENT_IMAGE_TAG=<immutable-workshop-v3-image-tag>
bash scripts/free5gc/00-run-all.sh
```

The full command creates chargeable AWS resources. Use `scripts/free5gc/99-cleanup.sh` when the dry run is complete.

## Architecture

### Shared Image, Two Workshop Roles

The source image supports three roles through `AGENT_ROLE`, but workshop-v3 deploys only ANDA and ANRA:

| Agent | Role | What It Does | Runs On |
|-------|------|--------------|---------|
| **ANPA** | Retained, disabled | Compatibility only; CloudFormation replaces this role in workshop-v3 | Not deployed |
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
   │     ├── ANRA: monitor Free5GC alarms → correlate → approval/SOP
   │     └── ANDA: watch DeploymentPlan CRDs → execute approved work
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

SOP 3 installs shared CRDs, ANDA, and ANRA after the Free5GC E2E gate. Use the complete, validated installer rather than installing individual charts manually:

```bash
export AGENT_IMAGE_REPOSITORY=<ECR_OR_PUBLIC_ECR_REPOSITORY>
export AGENT_IMAGE_TAG=<IMMUTABLE_SHA_TAG>
bash scripts/free5gc/04-deploy-monitoring-anra.sh
```

The umbrella chart also defaults `anpa.enabled=false` on this branch.

### Credential Pattern

The installer generates secret-backed Grafana and ANRA dashboard passwords when they do not exist and stores the generated values in owner-readable files on the bastion. The disposable workshop currently uses node-role credentials for Bedrock; replace this with EKS Pod Identity for non-workshop deployments.

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

### Publishing the Workshop Image

The publishing implementation lives in `scripts/publish-workshop-image.sh`. For a local release, authenticate with the workshop image account and run:

```bash
AWS_PROFILE=cse-dev-test scripts/publish-workshop-image.sh
```

The script verifies the `workshop-v3` branch, a clean working tree, successful local CI gates, AWS account `833542146025`, and the authoritative repository `public.ecr.aws/t2j9i5y9/anra-workshop` before building or pushing. It publishes immutable `<SHA>` and `workshop-v3-<SHA>` tags and prints the resulting digest and deployment exports. Use `--publish-dev` only for the moving test-loop tag. Use `--dry-run --skip-validation --allow-dirty` to inspect the plan without contacting AWS or Docker.

The GitHub `publish-workshop-image` job uses OIDC credentials and calls this same script after all CI gates pass; the workflow no longer carries a second copy of the build/push commands.

### Pipeline

- **Build system**: Hatch
- **CI**: GitHub Actions on `workshop-v3`
- **Image publisher**: `scripts/publish-workshop-image.sh`
- **Images**: immutable commit-SHA and `workshop-v3-<SHA>` tags; no `latest` publication
- **Coverage**: project threshold defined in `pyproject.toml`

## Technology Stack

| Layer | Tech |
|-------|------|
| **Agent Framework** | [Strands Agents SDK](https://github.com/strands-agents/sdk-python) + Amazon Bedrock (Claude) |
| **API** | FastAPI + Uvicorn |
| **Frontend** | React 18 + Ant Design + ReactFlow + Recharts |
| **Infrastructure** | AWS CloudFormation, Amazon VPC, EKS, Multus, gtp5g |
| **Provisioning** | CloudFormation plus SSM-driven cluster configuration |
| **5G Core** | Free5GC v4.2.3 |
| **5G traffic** | PacketRusher |
| **Monitoring** | Prometheus, Alertmanager, and Grafana |
| **Packaging** | Helm 3 |
| **CI/CD** | GitHub Actions |

## Further Reading

- [`docs/workshop-v3.md`](docs/workshop-v3.md) — Workshop-v3 contracts, security posture, and limitations
- [`docs/free5gc/LLD-Free5GC-on-AWS-EKS.md`](docs/free5gc/LLD-Free5GC-on-AWS-EKS.md) — Imported Free5GC infrastructure design
- [`docs/free5gc/Free5GC-Testing-Guide.md`](docs/free5gc/Free5GC-Testing-Guide.md) — Free5GC functional testing reference
- [`docs/runtime-architecture.md`](docs/runtime-architecture.md) — Agent startup and configuration architecture
- [`docs/deployment-orchestration.md`](docs/deployment-orchestration.md) — ANDA lifecycle and drain procedures
