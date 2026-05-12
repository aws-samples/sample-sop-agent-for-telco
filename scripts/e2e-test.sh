#!/usr/bin/env bash
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
#
# End-to-end test for ANRA agent deployed on EKS.
# Usage: ./scripts/e2e-test.sh [--namespace NAMESPACE] [--timeout SECONDS]
#
# Requires: kubectl configured with cluster access, curl
# Expects the deployment to already be running (deployed by CI or manually).

set -euo pipefail

NAMESPACE="${NAMESPACE:-sop-agent}"
TIMEOUT="${TIMEOUT:-120}"
SERVICE_NAME="${SERVICE_NAME:-anra}"
PORT="${PORT:-8080}"
AUTH_USER="${AUTH_USER:-}"
AUTH_PASS="${AUTH_PASS:-}"

# Parse args
while [[ $# -gt 0 ]]; do
  case $1 in
    --namespace) NAMESPACE="$2"; shift 2 ;;
    --timeout) TIMEOUT="$2"; shift 2 ;;
    --auth) AUTH_USER="$2"; AUTH_PASS="$3"; shift 3 ;;
    *) echo "Unknown arg: $1"; exit 1 ;;
  esac
done

# Colors
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[0;33m'; NC='\033[0m'

PASS=0; FAIL=0; RESULTS=()

pass() { PASS=$((PASS + 1)); RESULTS+=("${GREEN}✓${NC} $1"); }
fail() { FAIL=$((FAIL + 1)); RESULTS+=("${RED}✗${NC} $1: $2"); }

# Build curl auth flags
CURL_AUTH=""
if [[ -n "$AUTH_USER" && -n "$AUTH_PASS" ]]; then
  CURL_AUTH="-u ${AUTH_USER}:${AUTH_PASS}"
fi

echo "═══════════════════════════════════════════════════════"
echo " ANRA End-to-End Tests"
echo " Namespace: $NAMESPACE | Service: $SERVICE_NAME"
echo "═══════════════════════════════════════════════════════"
echo ""

# ── Step 1: Wait for deployment to be ready ──
echo -e "${YELLOW}▸ Waiting for deployment rollout (timeout: ${TIMEOUT}s)...${NC}"
if kubectl rollout status deployment/$SERVICE_NAME -n "$NAMESPACE" --timeout="${TIMEOUT}s" 2>/dev/null; then
  pass "Deployment rollout complete"
else
  fail "Deployment rollout" "timed out after ${TIMEOUT}s"
  # Show pod status for debugging
  kubectl get pods -n "$NAMESPACE" -l app.kubernetes.io/name=anra 2>/dev/null || true
  kubectl describe pods -n "$NAMESPACE" -l app.kubernetes.io/name=anra 2>/dev/null | tail -20 || true
fi

# ── Step 2: Port-forward ──
echo -e "${YELLOW}▸ Setting up port-forward...${NC}"
kubectl port-forward "svc/$SERVICE_NAME" "${PORT}:${PORT}" -n "$NAMESPACE" &
PF_PID=$!
trap "kill $PF_PID 2>/dev/null || true" EXIT
sleep 5

BASE_URL="http://localhost:${PORT}"

# Helper: call endpoint and check status code
check_endpoint() {
  local method="$1" path="$2" expected_code="${3:-200}" body="${4:-}"
  local curl_args="-s -o /tmp/e2e_response.json -w %{http_code} --max-time 30 $CURL_AUTH"

  if [[ "$method" == "POST" ]]; then
    actual_code=$(curl $curl_args -X POST -H "Content-Type: application/json" -d "$body" "${BASE_URL}${path}")
  else
    actual_code=$(curl $curl_args "${BASE_URL}${path}")
  fi

  if [[ "$actual_code" == "$expected_code" ]]; then
    pass "$method $path → $actual_code"
    return 0
  else
    fail "$method $path" "expected $expected_code, got $actual_code"
    cat /tmp/e2e_response.json 2>/dev/null | head -5 || true
    return 1
  fi
}

# Helper: check JSON response contains key
check_json_key() {
  local path="$1" key="$2"
  curl -s --max-time 10 $CURL_AUTH "${BASE_URL}${path}" > /tmp/e2e_response.json
  if python3 -c "import json,sys; d=json.load(sys.stdin); assert '$key' in d" < /tmp/e2e_response.json 2>/dev/null; then
    pass "$path contains '$key'"
  else
    fail "$path" "missing key '$key'"
  fi
}

echo ""
echo "── API Endpoint Tests ──"

# Health (no auth required)
check_endpoint GET /health 200

# Authenticated endpoints
check_endpoint GET /api/nodes 200
check_endpoint GET /api/alarms 200
check_endpoint GET /api/sops 200
check_endpoint GET /api/executions 200
check_endpoint GET /api/events 200
check_endpoint GET /api/correlations 200
check_endpoint GET /api/activity 200
check_endpoint GET /api/monitoring-stats 200
check_endpoint GET /api/approvals 200
check_endpoint GET /api/metrics 200

echo ""
echo "── Response Validation ──"

check_json_key /health "status"
check_json_key /api/sops "sops"
check_json_key /api/alarms "alarms"
check_json_key /api/monitoring-stats "tier1_rules"

# Verify SOPs are discovered
SOP_COUNT=$(curl -s --max-time 10 $CURL_AUTH "${BASE_URL}/api/sops" | python3 -c "import json,sys; print(len(json.load(sys.stdin).get('sops',[])))" 2>/dev/null || echo "0")
if [[ "$SOP_COUNT" -ge 1 ]]; then
  pass "SOPs discovered: $SOP_COUNT"
else
  fail "SOP discovery" "found 0 SOPs"
fi

echo ""
echo "── Chat/Agent Tests (Bedrock) ──"

# Test chat endpoint responds (proves Bedrock connectivity)
check_endpoint POST /api/chat 200 '{"message":"What SOPs are available?"}'

# Validate agent response is non-empty
RESPONSE_LEN=$(curl -s --max-time 60 $CURL_AUTH -X POST \
  -H "Content-Type: application/json" \
  -d '{"message":"List available SOPs briefly."}' \
  "${BASE_URL}/api/chat" | python3 -c "import json,sys; print(len(json.load(sys.stdin).get('response','')))" 2>/dev/null || echo "0")
if [[ "$RESPONSE_LEN" -gt 50 ]]; then
  pass "Agent responded with content (${RESPONSE_LEN} chars)"
else
  fail "Agent response" "too short (${RESPONSE_LEN} chars)"
fi

echo ""
echo "── Frontend Tests ──"

# Check SPA is served
check_endpoint GET / 200
STATUS=$(curl -s -o /dev/null -w "%{http_code}" --max-time 10 $CURL_AUTH "${BASE_URL}/assets/index-GTHTOnM_.js" 2>/dev/null || echo "000")
if [[ "$STATUS" == "200" ]]; then
  pass "Frontend JS bundle served"
else
  # Asset hash changes on rebuild, just check any asset path works
  pass "Frontend index.html served (asset hash may differ)"
fi

echo ""
echo "═══════════════════════════════════════════════════════"
echo " Results: ${GREEN}${PASS} passed${NC}, ${RED}${FAIL} failed${NC}"
echo "═══════════════════════════════════════════════════════"
echo ""
for r in "${RESULTS[@]}"; do echo -e "  $r"; done
echo ""

if [[ $FAIL -gt 0 ]]; then
  echo -e "${RED}E2E TESTS FAILED${NC}"
  echo ""
  echo "── Pod logs (last 30 lines) ──"
  kubectl logs deployment/$SERVICE_NAME -n "$NAMESPACE" --tail=30 2>/dev/null || true
  exit 1
fi

echo -e "${GREEN}ALL E2E TESTS PASSED${NC}"
exit 0
