# AgentCore Gateway — Tools Lambda

Phase 2 of the AgentCore migration: external Lambda + Gateway target for ANRA's telco tools (kubectl, SSM, InfluxDB).

> **Status:** Phase 2 spike. See [`../../../docs/AGENTCORE_PLAN.md`](../../../docs/AGENTCORE_PLAN.md).

## Why externalize tools?

In Phase 1, the agent runs in AgentCore Runtime with tools as in-process Python functions. That works, but couples tool execution to the agent VM.

Phase 2 moves tools to a dedicated Lambda exposed via AgentCore Gateway:

| Concern | In-process (Phase 1) | Gateway + Lambda (Phase 2) |
|---------|---------------------|----------------------------|
| Tool failure isolation | Tool crash takes down agent | Lambda failures contained |
| Network reach | Agent VM must have VPC config | Lambda gets VPC config; agent stays public |
| Scaling | Tied to agent session | Lambda scales independently |
| Identity | Single Runtime IAM role | Gateway's role + per-tool credential providers |
| Observability | Agent traces only | Gateway + Lambda + agent traces |
| Reusability | Agent-specific | Other AgentCore agents can use the same tools |
| Iteration | Redeploy agent | Update Lambda alone |

## What's in this directory

```
gateway/
├── README.md                  This file
├── lambda_tools/
│   └── handler.py             Lambda handler with kubectl/ssm/influxdb_query tools
├── tools.json                 MCP tool schema registered with Gateway
├── template.yaml              SAM template (Lambda + IAM + VPC config)
├── setup.sh                   One-shot setup: SAM deploy + Gateway + target
└── tests/
    └── test_handler.py        Unit tests (12 tests, no AWS required)
```

## Tools provided

| Tool | Purpose | Args |
|------|---------|------|
| `kubectl_command` | Run kubectl against the configured EKS cluster | `command: str` |
| `ssm_command` | Shell command on EC2 via SSM Run Command | `instance_id: str, command: str` |
| `influxdb_query` | Flux query against InfluxDB v2 | `flux: str` |

The handler enforces basic safety:

- Rejects kubectl commands containing shell metacharacters (`;`, `&`, `|`, backticks, `$()`)
- Polls SSM with a hard timeout (default 60s)
- Pulls the InfluxDB token from Secrets Manager (never logged)

## Local testing

Run the unit tests without any AWS resources:

```bash
cd deployments/agentcore/gateway
pip install pytest pytest-mock boto3 requests
python -m pytest tests/ -v
```

## Deployment

### Prerequisites

```bash
# AWS SAM CLI
pip install aws-sam-cli

# AgentCore CLI
npm install -g @aws/agentcore

# jq for the setup script
sudo apt-get install jq    # or brew install jq
```

You also need:

- An existing EKS cluster (for kubectl)
- Two private subnets in supported AgentCore AZs
- A security group allowing egress to EKS API + InfluxDB
- (Optional) Secrets Manager secret holding the InfluxDB token

### One-shot setup

```bash
export AWS_REGION=us-west-2
export EKS_CLUSTER_NAME=anra-workshop
export SUBNET_IDS=subnet-aaa,subnet-bbb
export SECURITY_GROUP_IDS=sg-xxx
export INFLUXDB_URL=https://influxdb.internal:8086    # optional
export INFLUXDB_TOKEN_SECRET_ID=anra/influxdb-token   # optional

cd deployments/agentcore/gateway
./setup.sh
```

This will:

1. SAM build + deploy the Lambda (`anra-agentcore-tools`) with VPC config
2. Create an AgentCore Gateway named `anra-tools-gw` (or reuse existing)
3. Add the Lambda as a target with the tool schema from `tools.json`
4. Print the tool names available via the Gateway

### Manual deployment (if you prefer step-by-step)

```bash
# 1. Build and deploy the Lambda
sam build --use-container
sam deploy --guided

# 2. Create the Gateway
agentcore add gateway --name anra-tools-gw --auth-type IAM

# 3. Register the Lambda as a target
agentcore add gateway-target \
  --gateway anra-tools-gw \
  --name anra-tools \
  --type lambda-function-arn \
  --lambda-arn $(aws cloudformation describe-stacks \
    --stack-name anra-agentcore-gateway-tools \
    --query 'Stacks[0].Outputs[?OutputKey==`ToolsFunctionArn`].OutputValue' \
    --output text) \
  --tool-schema-file tools.json
```

## How tools appear to the agent

Once registered, the Gateway exposes tools with the target name as a prefix and `___` delimiter:

- `anra-tools___kubectl_command`
- `anra-tools___ssm_command`
- `anra-tools___influxdb_query`

The Strands agent in `deployments/agentcore/main.py` discovers these via the standard MCP `tools/list` response from the Gateway.

## Next steps

- [ ] Wire `main.py` to use Gateway tools when `ANRA_GATEWAY_URL` env var is set
- [ ] Add Cedar policies for safety (Phase 3) — block `kubectl delete pod` in production namespaces
- [ ] Add additional tools as needed (Redfish BMC, ArgoCD, Prometheus alertmanager)

## References

- [AgentCore Gateway Lambda targets](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway-add-target-lambda.html)
- [Tool naming with target prefix](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway-tool-naming.html)
- [AgentCore Gateway VPC egress](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway-vpc-egress.html)
