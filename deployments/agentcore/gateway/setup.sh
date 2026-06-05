#!/usr/bin/env bash
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
#
# Provision the AgentCore Gateway with a Lambda target for ANRA tools.
#
# This script:
#   1. Builds and deploys the SAM template (Lambda + IAM)
#   2. Creates an AgentCore Gateway (or reuses an existing one)
#   3. Adds the Lambda function as a Gateway target with the tool schema
#   4. Outputs the Gateway URL for the agent to call
#
# Prerequisites:
#   - AWS SAM CLI: pip install aws-sam-cli
#   - AgentCore CLI: npm install -g @aws/agentcore
#   - jq

set -euo pipefail

STACK_NAME="${STACK_NAME:-anra-agentcore-gateway-tools}"
GATEWAY_NAME="${GATEWAY_NAME:-anra-tools-gw}"
TARGET_NAME="${TARGET_NAME:-anra-tools}"
REGION="${AWS_REGION:-us-west-2}"

# Required parameters (override via env)
EKS_CLUSTER_NAME="${EKS_CLUSTER_NAME:?Set EKS_CLUSTER_NAME env var}"
SUBNET_IDS="${SUBNET_IDS:?Set SUBNET_IDS env var (comma-separated)}"
SECURITY_GROUP_IDS="${SECURITY_GROUP_IDS:?Set SECURITY_GROUP_IDS env var (comma-separated)}"

INFLUXDB_URL="${INFLUXDB_URL:-}"
INFLUXDB_TOKEN_SECRET_ID="${INFLUXDB_TOKEN_SECRET_ID:-}"

cd "$(dirname "$0")"

echo "==> Validating prerequisites"
for cmd in sam aws agentcore jq; do
  command -v "$cmd" >/dev/null 2>&1 || {
    echo "ERROR: $cmd not found. See README for installation." >&2
    exit 1
  }
done
aws sts get-caller-identity >/dev/null
echo "    ✓ All prerequisites met"

echo "==> Step 1: SAM build"
sam build --use-container --template-file template.yaml

echo "==> Step 2: SAM deploy (stack: $STACK_NAME)"
sam deploy \
  --stack-name "$STACK_NAME" \
  --region "$REGION" \
  --capabilities CAPABILITY_IAM \
  --no-confirm-changeset \
  --no-fail-on-empty-changeset \
  --resolve-s3 \
  --parameter-overrides \
    "EksClusterName=$EKS_CLUSTER_NAME" \
    "InfluxdbUrl=$INFLUXDB_URL" \
    "InfluxdbTokenSecretId=$INFLUXDB_TOKEN_SECRET_ID" \
    "VpcSubnetIds=$SUBNET_IDS" \
    "VpcSecurityGroupIds=$SECURITY_GROUP_IDS"

LAMBDA_ARN=$(aws cloudformation describe-stacks \
  --stack-name "$STACK_NAME" \
  --region "$REGION" \
  --query 'Stacks[0].Outputs[?OutputKey==`ToolsFunctionArn`].OutputValue' \
  --output text)

echo "    ✓ Lambda deployed: $LAMBDA_ARN"

echo "==> Step 3: Create Gateway if it does not exist"
if agentcore list gateways 2>/dev/null | grep -q "\b$GATEWAY_NAME\b"; then
  echo "    ✓ Gateway '$GATEWAY_NAME' already exists, reusing"
else
  echo "    Creating new gateway '$GATEWAY_NAME'..."
  agentcore add gateway --name "$GATEWAY_NAME" --auth-type IAM
fi

echo "==> Step 4: Register Lambda as Gateway target"
agentcore add gateway-target \
  --gateway "$GATEWAY_NAME" \
  --name "$TARGET_NAME" \
  --type lambda-function-arn \
  --lambda-arn "$LAMBDA_ARN" \
  --tool-schema-file tools.json

echo ""
echo "==> Done. Summary:"
echo "    Lambda ARN:    $LAMBDA_ARN"
echo "    Gateway name:  $GATEWAY_NAME"
echo "    Target name:   $TARGET_NAME"
echo ""
echo "Tools available via Gateway:"
echo "  - ${TARGET_NAME}___kubectl_command"
echo "  - ${TARGET_NAME}___ssm_command"
echo "  - ${TARGET_NAME}___influxdb_query"
echo ""
echo "Test from the agent:"
echo "  agentcore invoke 'List the pods in the 5gc namespace using kubectl'"
