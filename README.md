# Strands SOP Agent

AI-powered Standard Operating Procedure (SOP) executor for NFV validation using [Strands Agents SDK](https://github.com/strands-agents/strands-agents-sdk-python) and Amazon Bedrock.

## What It Does

Reads SOPs from markdown files and executes them autonomously:
1. Parses SOP steps and expected outputs
2. Selects optimal Claude model based on complexity (Haiku → Sonnet → Opus)
3. Executes commands via kubectl, SSH, shell tools
4. Evaluates results against expected outputs
5. Auto-corrects failures with more capable models

## Quick Start

Deploy to any EKS cluster with a single command:

```bash
# Clone the repo
git clone <repo-url>
cd sample-sop-agent-for-strands

# Deploy (handles all prerequisites automatically)
./deploy.sh --cluster my-eks-cluster --region us-west-2

# Or with a specific AWS profile
./deploy.sh --cluster my-eks-cluster --region us-west-2 --profile my-profile

# Preview what will happen (dry-run)
./deploy.sh --cluster my-eks-cluster --dry-run
```

The deployment script uses an AI agent to execute the deployment SOP, automatically:
- Installing missing tools (AWS CLI, kubectl, Helm, Docker)
- Creating IAM roles for IRSA
- Building and pushing the Docker image to ECR
- Deploying via Helm
- Verifying the deployment

**Only requirement**: Python 3.11+ installed

## Prerequisites (handled automatically)

The deploy script will check and install these if missing:
- AWS CLI (configured with credentials)
- kubectl
- Helm 3
- Docker

You need:
- **AWS Account** with Bedrock enabled in your region
- **Bedrock Model Access** - Enable in [Bedrock Console](https://console.aws.amazon.com/bedrock/home#/modelaccess):
  - Claude 3.5 Haiku
  - Claude Sonnet 4
  - Claude Opus 4
- **EKS Cluster** (existing or the script can guide you to create one)

## Manual Deployment

If you prefer manual control, see [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md).

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
\`\`\`bash
kubectl get pods
\`\`\`
**Expected**: List of pods

### Step 2: Verify
\`\`\`bash
curl http://service/health
\`\`\`
**Expected**: `{"status":"ok"}`
```

See [sops/TEMPLATE.md](sops/TEMPLATE.md) for a complete template.

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    Web UI (React)                       │
├─────────────────────────────────────────────────────────┤
│                  Backend API (FastAPI)                  │
├─────────────────────────────────────────────────────────┤
│  SOP Graph (DAG)  │  SOP Executor  │  Adaptive Steering │
├───────────────────┴────────────────┴────────────────────┤
│              Strands Agents SDK + Bedrock               │
└─────────────────────────────────────────────────────────┘
         │                    │                    │
    ┌────▼────┐          ┌────▼────┐         ┌────▼────┐
    │ kubectl │          │   SSH   │         │  Shell  │
    └─────────┘          └─────────┘         └─────────┘
```

## Local Development

```bash
# Install dependencies
pip install -r requirements.txt

# Run backend
cd webui/backend
python api.py

# Run frontend (separate terminal)
cd webui/frontend
npm install && npm start
```

## Configuration

Environment variables:
- `BEDROCK_REGION`: AWS region for Bedrock (default: `us-west-2`)
- `BEDROCK_PROFILE`: AWS profile name (optional, uses default chain)
- `SOP_REPO`: Path to SOP files (default: `/app`)
- `APP_NAMESPACE`: Kubernetes namespace (default: `default`)

## License

MIT-0 - See [LICENSE](LICENSE)
