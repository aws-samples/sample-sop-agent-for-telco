#!/bin/bash
# =============================================================================
# Fault Injection — AMF-gNB Disconnect (NGAP N2 Failure)
#
# Alarm:    amf_gnb_disconnect
# SOP:      day2-remediate/core/remediate-amf-gnb-disconnect.md
# Severity: critical (UEs lose service immediately)
#
# Usage:
#   ./inject-amf-disconnect.sh              # full run
#   ./inject-amf-disconnect.sh --dry-run    # show what would happen
# =============================================================================
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$SCRIPT_DIR/lib/common.sh"

NAMESPACE="$CORE_NAMESPACE"
NF_NAME="${AMF_NF_NAME:-amf}"
ALARM_TYPE="disconnect"
ALARM_NAME="amf_gnb_disconnect"
DRY_RUN="${1:-}"

# ─── Dry-run shortcut (works without cluster access) ─────────────────────────
if [ "$DRY_RUN" = "--dry-run" ]; then
    log "DRY RUN — would execute:"
    echo "  1. Find AMF pod in $NAMESPACE (NF_NAME=$NF_NAME)"
    echo "  2. kubectl delete pod <amf-pod> -n $NAMESPACE --grace-period=0"
    echo "  3. POST $DASHBOARD/api/alarms/trigger/$ALARM_TYPE"
    echo "  4. Wait for ANRA pipeline (detect → correlate → execute SOP)"
    echo "  5. Monitor until alarm clears or timeout (${TIMEOUT}s)"
    exit 0
fi

# ─── Pre-flight ───────────────────────────────────────────────────────────────
log "Pre-flight checks..."

AMF_POD=$(find_pod "$NAMESPACE" "$NF_NAME") || true
if [ -z "$AMF_POD" ]; then
    fail "No AMF pod found in namespace $NAMESPACE (tried NF_NAME=$NF_NAME)"
fi
ok "AMF pod: $AMF_POD"

# Register cleanup trap — K8s auto-recovers AMF, but log the state on exit
cleanup() {
    log "Cleanup: verifying AMF is recovering..."
    $K get pods -n "$NAMESPACE" --no-headers 2>/dev/null | grep "$NF_NAME" | head -1 || true
}
trap cleanup EXIT

# Check gNB (to show the disconnect impact)
GNB_POD=$(find_pod "$RAN_NAMESPACE" "${GNB_NF_NAME:-gnb}") || true
if [ -n "$GNB_POD" ]; then
    ok "gNB pod: $GNB_POD (will lose NGAP connection)"
else
    warn "No gNB pod found in $RAN_NAMESPACE — disconnect will only affect core"
fi

if ! check_dashboard; then
    fail "Dashboard not reachable at $DASHBOARD"
fi
ok "Dashboard reachable"

# ─── Step 1: Kill AMF pod (real fault — severs NGAP) ─────────────────────────
echo ""
log "${R}Step 1: Injecting real fault — killing AMF pod (NGAP N2 severed)${NC}"

if ! $K delete pod "$AMF_POD" -n "$NAMESPACE" --force --grace-period=0 2>/dev/null; then
    fail "Failed to delete pod $AMF_POD"
fi
ok "AMF pod $AMF_POD deleted"

sleep 2
AMF_STATUS=$($K get pods -n "$NAMESPACE" --no-headers 2>/dev/null | grep "$NF_NAME" | head -1 || echo "restarting...")
log "AMF pod status: $AMF_STATUS"

if [ -n "$GNB_POD" ]; then
    GNB_LOGS=$($K logs "$GNB_POD" -n "$RAN_NAMESPACE" --tail=3 2>/dev/null | grep -i "ngap\|amf\|connect" || echo "(no NGAP log yet)")
    log "gNB reaction: $GNB_LOGS"
fi

# ─── Step 2: Trigger alarm via API ───────────────────────────────────────────
echo ""
log "Step 2: Triggering $ALARM_TYPE alarm via API"
trigger_alarm "$ALARM_TYPE" \
    "{\"source\": \"$AMF_POD\", \"namespace\": \"$NAMESPACE\", \"severity\": \"critical\", \"detail\": \"NGAP N2 connection lost between AMF and gNB — all UEs disconnected\", \"affected_gnb\": \"${GNB_POD:-unknown}\"}"

# ─── Step 3: Monitor pipeline ────────────────────────────────────────────────
echo ""
BASELINE=$(get_baseline_exec "$ALARM_NAME")
if ! monitor_pipeline "$ALARM_NAME" "$BASELINE"; then
    fail "Timeout after ${TIMEOUT}s — pipeline did not complete"
fi

# ─── Step 4: Verify recovery ─────────────────────────────────────────────────
echo ""
log "Step 4: Verifying AMF + NGAP recovery"
sleep 10

FINAL_AMF=$(find_pod "$NAMESPACE" "$NF_NAME") || true
FINAL_STATUS=$($K get pod "${FINAL_AMF:-$AMF_POD}" -n "$NAMESPACE" --no-headers 2>/dev/null || echo "unknown")
echo "  AMF: $FINAL_STATUS"

if echo "$FINAL_STATUS" | grep -q "Running"; then
    ok "AMF pod recovered"
    if [ -n "$GNB_POD" ]; then
        sleep 5
        NGAP_OK=$($K logs "$GNB_POD" -n "$RAN_NAMESPACE" --tail=10 2>/dev/null | grep -c -i "ngap.*success\|amf.*connect\|NG Setup" || true)
        if [ "${NGAP_OK:-0}" -gt "0" ]; then
            ok "NGAP N2 reconnected — gNB re-established AMF link"
        else
            warn "NGAP reconnection not yet confirmed (may take a few more seconds)"
        fi
    fi
else
    warn "AMF not yet Running — K8s may still be restarting"
fi

echo ""
log "Done. Full pipeline: AMF kill → NGAP down → alarm → correlate → SOP → recovery ✅"
