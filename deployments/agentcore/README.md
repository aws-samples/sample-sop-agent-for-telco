# ANRA on Amazon Bedrock AgentCore Runtime

This directory contains the ANRA agent packaged for deployment to **Amazon Bedrock AgentCore Runtime** — the managed serverless alternative to the EKS Helm deployment in `helm/anra/`.

> **Status:** Phase 1 spike. See [`docs/AGENTCORE_PLAN.md`](../../docs/AGENTCORE_PLAN.md) for the full migration plan.

## Why AgentCore?

| Capability | EKS deployment | AgentCore deployment |
|------------|----------------|----------------------|
| Infrastructure | Self-managed pod, IRSA, Helm | Fully managed microVM |
| Identity | IRSA | AgentCore Identity (Cognito/Okta/Entra) |
| Memory | In-pod / Git issues | AgentCore Memory (managed, multi-session) |
| Tool execution | In-process Python | Direct or via AgentCore Gateway (MCP) |
| Observability | Custom logging | AgentCore Observability (CloudWatch + OpenTelemetry) |
| Safety guardrails | Custom Python | AgentCore Policy (Cedar — declarative) |
| Evaluation | strands-agents-evals direct | AgentCore Evaluations (managed) |
| Cost model | Always-on EKS pod | Consumption-based (pay per invocation) |
| VPC connectivity | Native | GA — supported in us-west-2 + ap-northeast-1 |

## Prerequisites

Install the AgentCore CLI and `uv`:

```bash
# AgentCore CLI (Node.js based)
npm install -g @aws/agentcore

# uv (Python package manager)
curl -LsSf https://astral.sh/uv/install.sh | sh

# Verify
agentcore --version
uv --version
```

You'll also need:

- AWS account with Amazon Bedrock model access enabled (Claude Sonnet 4.0 minimum)
- An IAM execution role for AgentCore Runtime ([docs](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-permissions.html))
- A VPC with at least 2 private subnets in supported AgentCore AZs (only required if your tools need to reach private resources like InfluxDB or EKS API)

## Project layout

```
deployments/agentcore/
├── README.md           This file
├── pyproject.toml      uv-managed Python project
├── main.py             AgentCore entry point (@app.entrypoint)
├── agentcore.json      Deployment configuration template
├── deploy.sh           Helper script for deployment
└── tests/              Local tests for the entry point
```

## Local development

Test the agent locally (port 8080) without deploying:

```bash
cd deployments/agentcore

# Install dependencies
uv sync

# Run local dev server
uv run agentcore dev --no-browser
```

In another terminal, exercise each invocation pattern:

```bash
# 1. Free-form prompt
curl -X POST http://localhost:8080/invocations \
  -H "Content-Type: application/json" \
  -d '{"prompt": "List the SOPs available in this repository"}'

# 2. Run a named SOP
curl -X POST http://localhost:8080/invocations \
  -H "Content-Type: application/json" \
  -d '{"action": "run_sop", "sop": "deploy-5g-core", "model": "haiku"}'

# 3. Process Day-2 alarms (EventBridge pattern)
curl -X POST http://localhost:8080/invocations \
  -H "Content-Type: application/json" \
  -d '{"action": "process_alarms", "alarms": [{"name": "nf-crashloop", "namespace": "5gc", "severity": "high"}]}'
```

## Deploy to AgentCore Runtime

### Step 1: Configure deployment

Edit `agentcore.json` and replace the `REPLACE_WITH_*` placeholders:

- `executionRoleArn` — IAM role with permissions to call Bedrock, write CloudWatch Logs, etc.
- `subnetIds` — at least 2 private subnets in supported AZs
- `securityGroupIds` — security group allowing egress to your private services (InfluxDB, EKS API, etc.)

### Step 2: Deploy

```bash
agentcore deploy
```

This packages the agent code as a ZIP, uploads it to S3, and provisions the runtime.

### Step 3: Invoke

```bash
# Quick smoke test
agentcore invoke "What is the cluster health?"

# Or via boto3 / AWS CLI:
aws bedrock-agentcore-runtime invoke-agent-runtime \
  --agent-runtime-name anra-agent \
  --payload '{"action": "run_sop", "sop": "deploy-5g-core"}'
```

## Day 2 closed-loop pattern

For autonomous Day-2 remediation, schedule the agent via EventBridge:

```bash
# 1. Create an EventBridge rule that fires every 30s during business hours
aws events put-rule \
  --name anra-monitor-tick \
  --schedule-expression "rate(1 minute)" \
  --state ENABLED

# 2. Target the AgentCore runtime invocation
aws events put-targets \
  --rule anra-monitor-tick \
  --targets '[{
    "Id": "1",
    "Arn": "arn:aws:bedrock-agentcore-runtime:us-west-2:ACCOUNT:agent-runtime/anra-agent",
    "Input": "{\"action\": \"process_alarms\"}"
  }]'
```

## Open items (Phase 2+)

This spike covers the bare minimum: a Strands agent invokable via AgentCore Runtime. Remaining work tracked in [`docs/AGENTCORE_PLAN.md`](../../docs/AGENTCORE_PLAN.md):

- [ ] Phase 2: Migrate kubectl/SSM/Redfish tools to MCP servers behind AgentCore Gateway
- [ ] Phase 3: Add AgentCore Policy (Cedar) for VoNR safety guardrails
- [ ] Phase 4: EventBridge schedule + API Gateway webhook trigger
- [ ] Phase 5: Replace in-pod React UI with API Gateway → AgentCore + S3/CloudFront UI
- [ ] Phase 6: End-to-end validation against all 6 workshop SOPs

## References

- [AgentCore Runtime — Direct code deployment for Python](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-get-started-code-deploy-python.html)
- [AgentCore Runtime VPC configuration](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/agentcore-vpc.html)
- [AgentCore lifecycle settings](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-lifecycle-settings.html)
- [bedrock-agentcore-sdk-python](https://github.com/aws/bedrock-agentcore-sdk-python)
- [Strands Agents SDK](https://strandsagents.com/)
