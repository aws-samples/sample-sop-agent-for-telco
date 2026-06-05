#!/usr/bin/env bash
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
#
# Deploy ANRA agent to Amazon Bedrock AgentCore Runtime.
#
# Prerequisites:
#   - AgentCore CLI: npm install -g @aws/agentcore
#   - uv: curl -LsSf https://astral.sh/uv/install.sh | sh
#   - AWS credentials configured
#   - agentcore.json configured with VPC + IAM role
#
# Usage:
#   ./deploy.sh                    # deploy with current config
#   ./deploy.sh --dry-run          # show what would happen, no changes
#   ./deploy.sh --skip-validation  # skip prerequisite checks

set -euo pipefail

DRY_RUN=false
SKIP_VALIDATION=false
for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=true ;;
    --skip-validation) SKIP_VALIDATION=true ;;
    -h|--help)
      sed -n '/^#/,/^$/p' "$0" | head -20
      exit 0
      ;;
  esac
done

cd "$(dirname "$0")"

echo "==> Validating prerequisites"
if [[ "$SKIP_VALIDATION" == "false" ]]; then
  command -v agentcore >/dev/null 2>&1 || {
    echo "ERROR: agentcore CLI not found. Install with: npm install -g @aws/agentcore" >&2
    exit 1
  }
  command -v uv >/dev/null 2>&1 || {
    echo "ERROR: uv not found. Install with: curl -LsSf https://astral.sh/uv/install.sh | sh" >&2
    exit 1
  }
  command -v aws >/dev/null 2>&1 || {
    echo "ERROR: aws CLI not found." >&2
    exit 1
  }

  # Verify AWS credentials work
  if ! aws sts get-caller-identity >/dev/null 2>&1; then
    echo "ERROR: AWS credentials not configured or invalid." >&2
    exit 1
  fi
  echo "    ✓ All prerequisites met"
fi

echo "==> Checking agentcore.json for unfilled placeholders"
if grep -q "REPLACE_WITH_" agentcore.json; then
  echo "ERROR: agentcore.json still contains REPLACE_WITH_ placeholders. Edit it before deploying." >&2
  grep -n "REPLACE_WITH_" agentcore.json >&2
  exit 1
fi
echo "    ✓ Configuration looks good"

echo "==> Syncing dependencies (uv sync)"
if [[ "$DRY_RUN" == "false" ]]; then
  uv sync --quiet
fi

echo "==> Running pre-deployment tests"
if [[ "$DRY_RUN" == "false" && -d tests ]]; then
  uv run pytest tests/ -q || {
    echo "ERROR: pre-deployment tests failed." >&2
    exit 1
  }
fi

if [[ "$DRY_RUN" == "true" ]]; then
  echo ""
  echo "Dry run complete. The following would happen:"
  echo "  agentcore deploy"
  echo ""
  cat agentcore.json | python3 -m json.tool 2>/dev/null || cat agentcore.json
  exit 0
fi

echo "==> Deploying to AgentCore Runtime"
agentcore deploy

echo ""
echo "==> Deployment complete"
echo "Test with: agentcore invoke \"What is the cluster health?\""
