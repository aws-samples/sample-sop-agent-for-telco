#!/bin/bash
# =============================================================================
# E2E Test: Config Generation → SOP Deploy for site-002
#
# Validates the Phase 0 config generation pipeline:
#   1. Creates a DeploymentPlan CR with no pre-existing values
#   2. ANDA detects missing config + site descriptor present
#   3. Config gen AI agent generates values.yaml from site descriptor
#   4. SOP agent deploys with generated values
#   5. Verifies config output + CR status
#
# Prerequisites:
#   - KUBECONFIG pointing to site-002 cluster
#   - ANDA pod running with site descriptor mounted
#   - Bedrock access configured
#
# Usage:
#   ./test-config-gen-e2e.sh              # full run
#   ./test-config-gen-e2e.sh --dry-run    # show what would happen
#   ./test-config-gen-e2e.sh --cleanup    # remove test resources
# =============================================================================

set -euo pipefail

export KUBECONFIG="${KUBECONFIG:-/tmp/site002-kubeconfig}"
K="${KUBECTL:-/tmp/kubectl}"
ANDA_NS="anda-system"
NF_NAME="amf"
NF_NAMESPACE="open5gs"
NF_VENDOR="open5gs"
PLAN_NAME="test-config-gen-${NF_NAME}-$(date +%s)"
TIMEOUT=180

R='\033[0;31m'
G='\033[0;32m'
Y='\033[1;33m'
C='\033[0;36m'
NC='\033[0m'

log()  { echo -e "${C}[$(date +%H:%M:%S)]${NC} $1"; }
ok()   { echo -e "${G}  ✅ $1${NC}"; }
warn() { echo -e "${Y}  ⚠️  $1${NC}"; }
fail() { echo -e "${R}  ❌ $1${NC}"; }

FAILURES=0
assert() {
    local desc="$1" condition="$2"
    if eval "$condition"; then
        ok "PASS: $desc"
    else
        fail "FAIL: $desc"
        FAILURES=$((FAILURES + 1))
    fi
}

# ─── Cleanup mode ─────────────────────────────────────────────────────────────

if [ "${1:-}" = "--cleanup" ]; then
    log "Cleaning up test resources..."
    $K delete deploymentplan -n $ANDA_NS -l test=config-gen-e2e 2>/dev/null || true
    ANDA_POD=$($K get pods -n $ANDA_NS -l app.kubernetes.io/name=anda --no-headers -o custom-columns=":metadata.name" 2>/dev/null | head -1)
    if [ -n "$ANDA_POD" ]; then
        $K exec -n $ANDA_NS "$ANDA_POD" -- rm -f "/tmp/generated-configs/${NF_NAME}-values.yaml" 2>/dev/null || true
    fi
    ok "Cleanup complete"
    exit 0
fi

# ─── Pre-flight ───────────────────────────────────────────────────────────────

log "Pre-flight checks..."

ANDA_POD=$($K get pods -n $ANDA_NS -l app.kubernetes.io/name=anda --no-headers -o custom-columns=":metadata.name" 2>/dev/null | head -1)
assert "ANDA pod running" "[ -n '$ANDA_POD' ]"

# Check site descriptor exists in ANDA pod
SITE_DESC_EXISTS=$($K exec -n $ANDA_NS "$ANDA_POD" -- python -c "import os; print('yes' if any(os.path.isfile(p) for p in ['/app/config/site-descriptor.yaml', '/etc/anda/site-descriptor.yaml', '/app/configs/site-descriptors/docomo-site-002.yaml']) else 'no')" 2>/dev/null || echo "no")
assert "Site descriptor mounted in ANDA pod" "[ '$SITE_DESC_EXISTS' = 'yes' ]"

# Remove any pre-existing generated config (so Phase 0 triggers)
$K exec -n $ANDA_NS "$ANDA_POD" -- rm -f "/tmp/generated-configs/${NF_NAME}-values.yaml" 2>/dev/null || true
ok "Cleared pre-existing config for $NF_NAME"

if [ "${1:-}" = "--dry-run" ]; then
    log "DRY RUN — would create DeploymentPlan '$PLAN_NAME' for $NF_NAME"
    echo "  Intent: deploy, Vendor: $NF_VENDOR, Namespace: $NF_NAMESPACE"
    echo "  Expected: ANDA detects missing values, runs config gen agent"
    exit 0
fi

# ─── Step 1: Create DeploymentPlan CR ─────────────────────────────────────────

echo ""
log "Step 1: Creating DeploymentPlan CR '$PLAN_NAME'"

cat <<EOF | $K apply -f -
apiVersion: deployment.anda.aws.io/v1alpha1
kind: DeploymentPlan
metadata:
  name: $PLAN_NAME
  namespace: $ANDA_NS
  labels:
    test: config-gen-e2e
    triggered-by: test
spec:
  site: docomo-site-002
  cluster: site-002-workload
  intent: deploy
  reason: "E2E test: config generation from site descriptor"
  triggeredBy: operator
  priority: normal
  executionMode: live
  networkFunctions:
  - name: $NF_NAME
    type: $NF_VENDOR
    namespace: $NF_NAMESPACE
    action: deploy
    vendor: $NF_VENDOR
EOF

assert "DeploymentPlan CR created" "$K get deploymentplan $PLAN_NAME -n $ANDA_NS --no-headers 2>/dev/null | grep -q $PLAN_NAME"

# ─── Step 2: Wait for ANDA to process ────────────────────────────────────────

echo ""
log "Step 2: Waiting for ANDA to process (timeout: ${TIMEOUT}s)..."

START=$(date +%s)
LAST_PHASE=""

while true; do
    ELAPSED=$(( $(date +%s) - START ))
    if [ $ELAPSED -gt $TIMEOUT ]; then
        fail "Timeout after ${TIMEOUT}s"
        break
    fi

    PHASE=$($K get deploymentplan "$PLAN_NAME" -n $ANDA_NS -o jsonpath='{.status.phase}' 2>/dev/null || echo "")

    if [ -n "$PHASE" ] && [ "$PHASE" != "$LAST_PHASE" ]; then
        echo -e "  ${C}[+${ELAPSED}s]${NC} Phase: ${Y}${PHASE}${NC}"
        LAST_PHASE="$PHASE"
    fi

    case "$PHASE" in
        Completed|PartiallyCompleted)
            ok "ANDA completed processing"
            break
            ;;
        Failed|PartiallyFailed|TimedOut)
            MSG=$($K get deploymentplan "$PLAN_NAME" -n $ANDA_NS -o jsonpath='{.status.message}' 2>/dev/null || echo "")
            warn "ANDA finished with phase: $PHASE — $MSG"
            break
            ;;
    esac

    sleep 5
done

# ─── Step 3: Verify config was generated ─────────────────────────────────────

echo ""
log "Step 3: Verifying config generation output..."

CONFIG_EXISTS=$($K exec -n $ANDA_NS "$ANDA_POD" -- test -f "/tmp/generated-configs/${NF_NAME}-values.yaml" 2>/dev/null && echo "yes" || echo "no")
assert "Generated values file exists" "[ '$CONFIG_EXISTS' = 'yes' ]"

if [ "$CONFIG_EXISTS" = "yes" ]; then
    # Show first 20 lines of generated config
    echo ""
    log "Generated ${NF_NAME}-values.yaml (first 20 lines):"
    $K exec -n $ANDA_NS "$ANDA_POD" -- head -20 "/tmp/generated-configs/${NF_NAME}-values.yaml" 2>/dev/null | sed 's/^/  /'

    # Check for site-specific values from docomo-site-002 descriptor
    CONFIG_CONTENT=$($K exec -n $ANDA_NS "$ANDA_POD" -- cat "/tmp/generated-configs/${NF_NAME}-values.yaml" 2>/dev/null)

    # These values should come from the site descriptor (mcc=440, mnc=10 for Docomo)
    echo ""
    log "Checking site-specific values..."
    echo "$CONFIG_CONTENT" | grep -qiE 'mcc[^0-9]*440([^0-9]|$)' && ok "PLMN MCC 440 found" || warn "MCC 440 not found in config"
    echo "$CONFIG_CONTENT" | grep -qiE 'mnc[^0-9]*10([^0-9]|$)' && ok "PLMN MNC 10 found" || warn "MNC 10 not found in config"
fi

# ─── Step 4: Verify CR status tracking ───────────────────────────────────────

echo ""
log "Step 4: Verifying CR status has config generation metadata..."

CONFIG_GENERATED=$($K get deploymentplan "$PLAN_NAME" -n $ANDA_NS -o jsonpath="{.status.sopExecution.${NF_NAME}.configGenerated}" 2>/dev/null || echo "")
VALUES_PATH=$($K get deploymentplan "$PLAN_NAME" -n $ANDA_NS -o jsonpath="{.status.sopExecution.${NF_NAME}.valuesPath}" 2>/dev/null || echo "")
DURATION=$($K get deploymentplan "$PLAN_NAME" -n $ANDA_NS -o jsonpath="{.status.sopExecution.${NF_NAME}.configGenDuration}" 2>/dev/null || echo "")

assert "CR status.sopExecution.${NF_NAME}.configGenerated == true" "[ '$CONFIG_GENERATED' = 'true' ]"
assert "CR status has valuesPath" "[ -n '$VALUES_PATH' ]"
assert "CR status has configGenDuration" "[ -n '$DURATION' ]"

if [ -n "$VALUES_PATH" ]; then
    ok "Values path: $VALUES_PATH"
fi
if [ -n "$DURATION" ]; then
    ok "Config gen duration: $DURATION"
fi

# ─── Step 5: Check ANDA logs for config gen activity ─────────────────────────

echo ""
log "Step 5: Checking ANDA logs for config generation activity..."

LOGS=$($K logs -n $ANDA_NS "$ANDA_POD" --tail=50 2>/dev/null | grep -i "config gen\|Phase 0\|generated.*config\|site descriptor" | tail -5)
if [ -n "$LOGS" ]; then
    ok "Config gen activity found in logs:"
    echo "$LOGS" | sed 's/^/  /'
else
    warn "No config gen log entries found in last 50 lines"
fi

# ─── Summary ──────────────────────────────────────────────────────────────────

echo ""
echo "═══════════════════════════════════════════════════"
if [ $FAILURES -eq 0 ]; then
    echo -e " ${G}ALL ASSERTIONS PASSED${NC}"
else
    echo -e " ${R}${FAILURES} ASSERTION(S) FAILED${NC}"
fi
echo "═══════════════════════════════════════════════════"
echo ""
echo "  Plan:     $PLAN_NAME"
echo "  NF:       $NF_NAME ($NF_VENDOR)"
echo "  Phase:    $LAST_PHASE"
echo "  Duration: ${ELAPSED}s"
echo ""
echo "  Cleanup:  $0 --cleanup"
echo ""

exit $FAILURES
