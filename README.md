# Sample SOP Agent for Telco

[![CI](https://github.com/aws-samples/sample-sop-agent-for-telco/actions/workflows/ci.yml/badge.svg)](https://github.com/aws-samples/sample-sop-agent-for-telco/actions/workflows/ci.yml)
[![License: MIT-0](https://img.shields.io/badge/License-MIT--0-blue.svg)](LICENSE)

> **⚠️ Important:** This is sample code for demonstration and learning purposes. You should work with your security and legal teams to meet your organizational security, regulatory, and compliance requirements before deploying to production environments.

AI-powered Standard Operating Procedure (SOP) executor for telco network function deployment, validation, and autonomous remediation. Built with the [Strands Agents SDK](https://github.com/strands-agents/sdk-python) and Amazon Bedrock.

This repository implements two complementary agents that share the same Strands + Bedrock backend:

- **ANDA (Automated Network Deployment Agent)** — Day-1 SOP execution: deploy 5G network functions, validate end-to-end connectivity, configure monitoring.
- **ANRA (Autonomous Network Remediation Agent)** — Day-2 closed-loop operations: detect alarms via Telegraf metrics, correlate with topology graph for root-cause analysis, and execute remediation SOPs autonomously.

## What It Does

Reads SOPs from markdown files and executes them autonomously:

1. Parses SOP steps and expected outputs (RFC 2119 constraint format supported)
2. Dynamically discovers available Claude models and selects by complexity tier (fast → balanced → powerful)
3. Executes commands via kubectl, SSH, AWS SSM, Redfish, shell tools
4. Evaluates results against expected outputs using Strands Evals SDK
5. Auto-corrects failures by escalating to a more capable model
6. Correlates alerts across multiple sources and generates remediation SOPs

## Architecture

![SOP Agent architecture: Operator interacts with the Web Interface (FastAPI + React UI), which routes through the Strands Agents SDK (SOP Graph, SOP Executor, Adaptive Steering). The executor uses MCP tools (kubectl, SSH, Shell) to operate on Amazon EKS. Adaptive Steering selects Claude Haiku for simple tasks, Sonnet for complex tasks, and Opus for fix-mode escalation via Amazon Bedrock.](docs/images/architecture.png)

**Components:**

- **Web Interface** — FastAPI backend + React UI for operator interaction
- **Strands Agents SDK** — orchestrates SOP execution with three layers:
  - **SOP Graph (DAG Engine)** — parses SOPs into a directed acyclic graph
  - **SOP Executor** — executes steps via MCP tools (kubectl, SSH, Shell)
  - **Adaptive Steering** — selects optimal Claude model based on step complexity
- **Amazon Bedrock** — hosts Claude Haiku ($1/1M tokens) → Sonnet ($6/1M) → Opus ($30/1M) for adaptive cost optimization
- **Amazon EKS** — target cluster running network functions (Helm charts, Services, NF Pods)

## Quick Start

### Prerequisites

- **AWS Account** with [Amazon Bedrock](https://aws.amazon.com/bedrock/) enabled
- **Bedrock Model Access** — at least one Anthropic Claude model enabled. Visit the [Bedrock Console](https://console.aws.amazon.com/bedrock/) to enable model access.
- **EKS Cluster** with `kubectl` configured (or any Kubernetes cluster)
- **Helm 3** installed
- **Python 3.11+** for local development

### Deploy with Helm (using public image)

The fastest path — uses the pre-built public image:

```bash
helm upgrade --install anra helm/anra/ \
  --namespace anra --create-namespace \
  --set image.repository=public.ecr.aws/k6b9y4d0/sample-sop-agent-for-telco \
  --set image.tag=latest \
  --set bedrock.region=us-west-2
```

### Build your own image

If you want to customize the agent or build from source:

```bash
# Clone the repo
git clone https://github.com/aws-samples/sample-sop-agent-for-telco.git
cd sample-sop-agent-for-telco

# Build and push to your ECR
ECR_URI="<account-id>.dkr.ecr.<region>.amazonaws.com/anra"
docker build -t anra:latest .
docker tag anra:latest $ECR_URI:latest
docker push $ECR_URI:latest

# Deploy via Helm
helm upgrade --install anra helm/anra/ \
  --namespace anra --create-namespace \
  --set image.repository=$ECR_URI \
  --set image.tag=latest \
  --set bedrock.region=us-west-2
```

The agent auto-discovers available Bedrock models at startup — no model IDs need to be configured.

## Writing SOPs

SOPs are markdown files in the `sops/` directory. The agent supports two formats:

- **Simple format** — bullet-style steps (good for quick prototypes)
- **RFC 2119 format** — structured with explicit `MUST` / `SHOULD` constraints (recommended for production agent SOPs)

Minimal example:

````markdown
# My SOP Title

## Overview
Brief description of what this SOP does.

## Prerequisites
- Required access/tools

## Steps

### Step 1: Do something
```tool: kubectl
kubectl get pods -n my-namespace
```
**Expected**: List of pods in `Running` state

### Step 2: Verify
```tool: shell
curl http://service/health
```
**Expected**: `{"status":"ok"}`
````

See [sops/TEMPLATE.md](sops/TEMPLATE.md) for the complete template, or [sops/workshop-deploy/](sops/workshop-deploy/) for real-world RFC 2119 examples.

## Project Structure

```
agent/                       Core Python application
├── api.py                   FastAPI app wiring + middleware
├── routers/                 API endpoints (9 modules)
├── sop_executor.py          SOP execution engine + tools
├── sop_graph.py             Multi-agent DAG orchestrator
├── model_discovery.py       Dynamic Bedrock model probing
├── monitor.py               Day-2 alert monitoring + remediation
├── correlator.py            Event correlation engine
├── config.py                Centralized YAML-driven configuration
└── adaptive_steering.py     Just-in-time tool interception

evals/                       Deterministic evaluators (no LLM judge)
webui/frontend/              React UI (Vite + React 19)
helm/anra/                   Helm chart for Kubernetes deployment
sops/                        SOP markdown files (deploy + remediate)
alarm-references/            Structured alarm definitions (YAML/JSON)
gitops/                      ArgoCD application definitions
configs/                     InfluxDB + Telegraf configurations
tests/                       Unit + integration tests (209 passing)
docs/images/                 Architecture diagrams
```

## Local Development

```bash
# Install dependencies
pip install -r requirements.txt
pip install pytest pytest-asyncio pytest-mock  # for testing

# Run the backend (API + monitor)
python entrypoint.py

# Run frontend (separate terminal)
cd webui/frontend
npm install && npm run dev
```

The frontend dev server proxies API requests to `localhost:8080`.

## Configuration

Primary config: [`anra-config.yaml`](anra-config.yaml) — defines cluster, nodes, alarms, and monitoring rules.

Environment variables (override config):

| Variable | Default | Purpose |
|----------|---------|---------|
| `BEDROCK_REGION` | `us-west-2` | AWS region for Bedrock model invocation |
| `BEDROCK_PROFILE` | (default chain) | AWS profile name |
| `BEDROCK_ROLE_ARN` | (none) | IAM role to assume for Bedrock (used in Workshop Studio environments) |
| `SOP_REPO` | project root | Path to SOP markdown files |
| `APP_NAMESPACE` | `default` | Target Kubernetes namespace for SOP execution |
| `AUTH_USERNAME` / `AUTH_PASSWORD` | (none) | HTTP Basic Auth for the web UI |

## Running Tests

```bash
python -m pytest tests/ -v
```

All 209 tests should pass on Python 3.11 and 3.12.

## CI/CD

This repository uses two GitHub Actions workflows:

- **[`ci.yml`](.github/workflows/ci.yml)** — runs on every push and pull request: unit tests (matrix Python 3.11/3.12), code quality (ruff), security (bandit, semgrep), Docker build, Helm chart validation, container smoke test, and end-to-end test on a [kind](https://kind.sigs.k8s.io/) cluster.
- **[`release.yml`](.github/workflows/release.yml)** — manual or tag-triggered: builds and pushes to public ECR, optionally runs E2E test on a real EKS cluster (requires maintainer secrets).

## Security

See [SECURITY.md](SECURITY.md) for vulnerability reporting and supported versions.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

## License

This sample code is licensed under the MIT-0 License. See the [LICENSE](LICENSE) file.

## Disclaimer

This is sample code, for non-production usage. You are responsible for testing, securing, and optimizing the code as appropriate for production-grade use based on your specific quality control practices and standards. Deploying this code may incur AWS charges for creating or using AWS chargeable resources, such as running Amazon EC2 instances, using Amazon Bedrock, or Amazon EKS clusters.
