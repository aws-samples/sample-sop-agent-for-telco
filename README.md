# Sample Telco SOP Agent for Strands

> **⚠️ Important:** This is sample code for demonstration and learning purposes. You should work with your security and legal teams to meet your organizational security, regulatory, and compliance requirements before deploying to production environments.

AI-powered Standard Operating Procedure (SOP) executor for telco network function validation using [Strands Agents SDK](https://github.com/strands-agents/sdk-python) and Amazon Bedrock.

## What It Does

Reads SOPs from markdown files and executes them autonomously:
1. Parses SOP steps and expected outputs
2. Dynamically discovers available Claude models and selects by complexity tier (fast → balanced → powerful)
3. Executes commands via kubectl, SSH, SSM, Redfish, shell tools
4. Evaluates results against expected outputs
5. Auto-corrects failures with more capable models
6. Correlates alerts across multiple sources and generates remediation SOPs

## Quick Start

### Prerequisites

- **AWS Account** with Bedrock enabled in your region
- **Bedrock Model Access** — At least one Anthropic Claude model enabled (the agent auto-discovers available models at startup). Visit the [Bedrock Console](https://console.aws.amazon.com/bedrock/) to submit the Anthropic use case form if prompted.
- **EKS Cluster** with kubectl configured
- **Helm 3** installed
- **Docker** installed (for building the container image)

### Deploy with Helm

```bash
# Clone the repo
git clone https://github.com/aws-samples/sample-sop-agent-for-telco.git
cd sample-sop-agent-for-telco

# Build and push the container image
ECR_URI="<account-id>.dkr.ecr.<region>.amazonaws.com/anra"
docker build -t anra:latest .
docker tag anra:latest $ECR_URI:latest
docker push $ECR_URI:latest

# Deploy via Helm
helm upgrade --install anra helm/anra/ \
  --namespace anra --create-namespace \
  --set image.repository=$ECR_URI \
  --set image.tag=latest \
  --set env.BEDROCK_REGION=us-west-2
```

The agent will auto-discover available Bedrock models at startup — no model IDs need to be configured.

## Writing SOPs

SOPs are markdown files in the `sops/` directory:

```markdown
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
**Expected**: List of pods in Running state

### Step 2: Verify
```tool: shell
curl http://service/health
```
**Expected**: `{"status":"ok"}`
```

See [sops/TEMPLATE.md](sops/TEMPLATE.md) for a complete template, or the [workshop SOPs](sops/workshop-deploy/) for real-world examples.

## Architecture

```mermaid
flowchart TB
    UI["Web UI (React + Vite)"]
    API["Backend API (FastAPI) — agent/api.py<br/>Routers: alarms, chat, metrics, sops, health, timeline, webhooks"]

    subgraph CORE["Agent Core"]
        direction LR
        GRAPH["SOP Graph (DAG)"]
        EXEC["SOP Executor"]
        STEER["Adaptive Steering"]
    end

    subgraph DAY2["Day-2 Operations"]
        direction LR
        MON["Monitor"]
        CORR["Correlator"]
        DISC["Model Discovery"]
    end

    SDK["Strands Agents SDK + Amazon Bedrock"]

    UI --> API
    API --> CORE
    CORE --> DAY2
    DAY2 --> SDK

    SDK --> KUBECTL["kubectl"]
    SDK --> SSH["SSH"]
    SDK --> SSM["AWS SSM"]
    SDK --> REDFISH["Redfish"]
```

## Project Structure

```
agent/                  # Core Python application
├── api.py              # FastAPI app wiring + middleware
├── routers/            # API endpoints (9 modules)
├── sop_executor.py     # SOP execution engine + tools
├── sop_graph.py        # Multi-agent DAG orchestrator
├── model_discovery.py  # Dynamic Bedrock model probing
├── monitor.py          # Day-2 alert monitoring + remediation
├── correlator.py       # Event correlation engine
├── config.py           # Centralized YAML-driven configuration
└── adaptive_steering.py # Just-in-time tool interception

evals/                  # Deterministic evaluators (no LLM judge)
frontend/               # React UI (webui/frontend/)
helm/anra/              # Helm chart for Kubernetes deployment
sops/                   # SOP markdown files
alarm-references/       # Structured alarm definitions (YAML/JSON)
gitops/                 # ArgoCD application definitions
configs/                # InfluxDB + Telegraf configs
tests/                  # Unit + integration tests (209 passing)
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
- `BEDROCK_REGION`: AWS region for Bedrock (default: `us-west-2`)
- `BEDROCK_PROFILE`: AWS profile name (optional, uses default credential chain)
- `SOP_REPO`: Path to SOP files (default: project root)
- `APP_NAMESPACE`: Target Kubernetes namespace for SOP execution
- `AUTH_USERNAME` / `AUTH_PASSWORD`: HTTP Basic Auth for the web UI

## Running Tests

```bash
python -m pytest tests/ -v
```

## License

This sample code is licensed under the MIT-0 License. See the [LICENSE](LICENSE) file.

## Security

See [CONTRIBUTING](CONTRIBUTING.md#security-issue-notifications) for more information.

## Disclaimer

This is sample code, for non-production usage. You are responsible for testing, securing, and optimizing the code as appropriate for production grade use based on your specific quality control practices and standards. Deploying this code may incur AWS charges for creating or using AWS chargeable resources, such as running Amazon EC2 instances, using Amazon Bedrock, or Amazon EKS clusters.
