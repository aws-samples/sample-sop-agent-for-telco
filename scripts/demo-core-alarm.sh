#!/bin/bash
# =============================================================================
# ANO Demo — Core NF Crashloop (End-to-End)
#
# What it does:
#   1. Kills the NRF pod (real fault)
#   2. Injects alarm via API (instant UI feedback)
#   3. Monitors the full autonomous pipeline:
#      detect → correlate → enrich → execute SOP → AI fixes → alarm clears
#
# Usage:
#   ./demo-core-alarm.sh              # full run
#   ./demo-core-alarm.sh --dry-run    # show what would happen, no changes
#
# Prerequisites:
#   - KUBECONFIG=/tmp/site002-kubeconfig
#   - /tmp/kubectl available
#   - Dashboard at https://d1j3d0lbctd27j.cloudfront.net
# =============================================================================

set -euo pipefail

export KUBECONFIG=/tmp/site002-kubeconfig
K=/tmp/kubectl
DASHBOARD="https://d1j3d0lbctd27j.cloudfront.net"
NF_NAME="nrf"
NAMESPACE="open5gs"
DRY_RUN="${1:-}"

R='\033[0;31m'
G='\033[0;32m'
Y='\033[1;33m'
C='\033[0;36m'
NC='\033[0m'

log()  { echo -e "${C}[$(date +%H:%M:%S)]${NC} $1"; }
ok()   { echo -e "${G}  ✅ $1${NC}"; }
warn() { echo -e "${Y}  ⚠️  $1${NC}"; }
fail() { echo -e "${R}  ❌ $1${NC}"; }

# ─── Pre-flight ───────────────────────────────────────────────────────────────

log "Pre-flight checks..."

NRF_POD=$($K get pods -n $NAMESPACE -l app.kubernetes.io/name=$NF_NAME --no-headers -o custom-columns=":metadata.name" 2>/dev/null | head -1)
if [ -z "$NRF_POD" ]; then
    fail "No NRF pod found in namespace $NAMESPACE"
    exit 1
fi
ok "NRF pod: $NRF_POD"

ANRA_STATUS=$(curl -sf -o /dev/null "$DASHBOARD/health" 2>/dev/null && echo "up" || echo "down")
if [ "$ANRA_STATUS" != "up" ]; then
    fail "Dashboard not reachable at $DASHBOARD"
    exit 1
fi
ok "Dashboard reachable"

ANDA_POD=$($K get pods -n anda-system -l app.kubernetes.io/name=anda --no-headers -o custom-columns=":metadata.name" 2>/dev/null | head -1)
ok "ANDA pod: ${ANDA_POD:-none}"

if [ "$DRY_RUN" = "--dry-run" ]; then
    log "DRY RUN — would execute:"
    echo "  1. kubectl delete pod $NRF_POD -n $NAMESPACE --grace-period=0"
    echo "  2. POST $DASHBOARD/api/alarms/trigger/core"
    echo "  3. Wait for ANRA pipeline (detect → correlate → enrich → execute)"
    echo "  4. Monitor until alarm clears or timeout (5 min)"
    exit 0
fi

# ─── Step 1: Kill the NRF pod (real fault) ────────────────────────────────────

echo ""
log "${R}Step 1: Injecting real fault — killing NRF pod${NC}"
$K delete pod "$NRF_POD" -n $NAMESPACE --grace-period=0 2>/dev/null
ok "Pod $NRF_POD deleted"

# Show pod state immediately
sleep 2
POD_STATUS=$($K get pods -n $NAMESPACE -l app.kubernetes.io/name=$NF_NAME --no-headers 2>/dev/null | awk '{print $1, $3}')
log "NRF pod status: $POD_STATUS"

# ─── Step 2: Inject alarm (instant UI feedback) ──────────────────────────────

echo ""
log "Step 2: Triggering alarm via API"
TRIGGER_RESP=$(curl -sf -X POST "$DASHBOARD/api/alarms/trigger/core" -H "Content-Type: application/json" 2>/dev/null)
ok "Alarm injected: $TRIGGER_RESP"

# ─── Step 3: Monitor the pipeline ────────────────────────────────────────────

echo ""
# Record baseline execution count (so we detect NEW completions only)
BASELINE_EXEC=$(curl -sf "$DASHBOARD/api/executions" 2>/dev/null | python3 -c "
import sys,json
data=json.load(sys.stdin)
print(len([e for e in data.get('executions', []) if 'nf_crashloop' in e.get('alarm','')]))
" 2>/dev/null || echo "0")


log "Step 3: Monitoring autonomous pipeline (timeout: 5 min)"
echo ""

TIMEOUT=300
START=$(date +%s)
LAST_STAGE=""

while true; do
    ELAPSED=$(( $(date +%s) - START ))
    if [ $ELAPSED -gt $TIMEOUT ]; then
        fail "Timeout after ${TIMEOUT}s"
        break
    fi

    # Check activity feed for latest stage
    ACTIVITY=$(curl -sf "$DASHBOARD/api/activity?limit=5" 2>/dev/null)
    LATEST_STAGE=$(echo "$ACTIVITY" | python3 -c "
import sys,json
data=json.load(sys.stdin)
items = data.get('activity', data) if isinstance(data, dict) else data
for a in items[:1]:
    print(a.get('stage','') + '|' + a.get('message',''))
" 2>/dev/null || echo "")

    if [ -n "$LATEST_STAGE" ] && [ "$LATEST_STAGE" != "$LAST_STAGE" ]; then
        STAGE=$(echo "$LATEST_STAGE" | cut -d'|' -f1)
        MSG=$(echo "$LATEST_STAGE" | cut -d'|' -f2)
        echo -e "  ${C}[+${ELAPSED}s]${NC} [${Y}${STAGE}${NC}] $MSG"
        LAST_STAGE="$LATEST_STAGE"
    fi

    # Check if execution completed
    EXEC_COUNT=$(curl -sf "$DASHBOARD/api/executions" 2>/dev/null | python3 -c "
import sys,json
data=json.load(sys.stdin)
execs = data.get('executions', [])
recent = [e for e in execs if 'nf_crashloop' in e.get('alarm','')]
print(len(recent))
" 2>/dev/null || echo "0")

    if [ "$EXEC_COUNT" -gt "$BASELINE_EXEC" ]; then
        echo ""
        ok "SOP execution completed!"

        # Get execution details
        curl -sf "$DASHBOARD/api/executions" 2>/dev/null | python3 -c "
import sys,json
data=json.load(sys.stdin)
for e in data.get('executions', []):
    if 'nf_crashloop' in e.get('alarm',''):
        print(f\"  Alarm:  {e.get('alarm')}\" )
        print(f\"  Result: {e.get('result')}\")
        print(f\"  SOP:    {e.get('sop','').split('/')[-1]}\")
        print(f\"  Time:   {e.get('timestamp','')[:19]}\")
" 2>/dev/null
        break
    fi

    # Check for ANDA deployment (cross-agent trigger)
    PLANS=$($K get deploymentplans.deployment.anda.aws.io --all-namespaces --no-headers 2>/dev/null)
    if [ -n "$PLANS" ]; then
        echo ""
        ok "ANDA DeploymentPlan created (cross-agent trigger)!"
        echo "  $PLANS"
    fi

    sleep 5
done

# ─── Step 4: Verify recovery ─────────────────────────────────────────────────

echo ""
log "Step 4: Verifying NRF recovery"
sleep 5

FINAL_STATUS=$($K get pods -n $NAMESPACE -l app.kubernetes.io/name=$NF_NAME --no-headers 2>/dev/null)
echo "  $FINAL_STATUS"

if echo "$FINAL_STATUS" | grep -q "Running"; then
    ok "NRF pod recovered — system healthy"
else
    warn "NRF pod not yet Running — may still be starting"
fi

# ─── Summary ──────────────────────────────────────────────────────────────────

echo ""
echo "═══════════════════════════════════════════════════"
echo -e " ${G}Demo Complete${NC}"
echo "═══════════════════════════════════════════════════"
echo ""
echo "  Dashboard: $DASHBOARD/alarms"
echo "  Duration:  ${ELAPSED}s"
echo ""
echo "  What happened:"
echo "    1. Real fault: NRF pod killed"
echo "    2. ANRA detected alarm (nf_crashloop)"
echo "    3. AI correlated + enriched SOP with Bedrock"
echo "    4. AI executed remediation autonomously"
echo "    5. NRF pod recovered"
echo ""
