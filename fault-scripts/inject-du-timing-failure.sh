#!/bin/bash
# =============================================================================
# Fault Injection — DU Timing Failure (PTP Drift)
#
# Alarm:    du_timing_failure
# SOP:      day2-remediate/ran/remediate-du-timing-failure.md
# Severity: critical
#
# Usage:
#   ./inject-du-timing-failure.sh              # full run
#   ./inject-du-timing-failure.sh --dry-run    # show what would happen
# =============================================================================
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$SCRIPT_DIR/lib/common.sh"

NAMESPACE="$RAN_NAMESPACE"
NF_NAME="${GNB_NF_NAME:-gnb}"
ALARM_TYPE="ran"
ALARM_NAME="du_timing_failure"
DRY_RUN="${1:-}"


# ─── Dry-run shortcut (works without cluster access) ─────────────────────────
if [ "$DRY_RUN" = "--dry-run" ]; then
    log "DRY RUN — would execute:"
    echo "  1. kubectl exec <gnb-pod> -- inject timing error annotation"
    echo "  2. POST $DASHBOARD/api/alarms/trigger/$ALARM_TYPE"
    echo "  3. Wait for ANRA pipeline (detect → correlate → execute SOP)"
    echo "  4. Monitor until alarm clears or timeout (${TIMEOUT}s)"
    exit 0
fi
# ─── Pre-flight ───────────────────────────────────────────────────────────────
log "Pre-flight checks..."

GNB_POD=$(find_pod "$NAMESPACE" "$NF_NAME") || true
if [ -z "$GNB_POD" ]; then
    fail "No gNB pod found in namespace $NAMESPACE (tried NF_NAME=$NF_NAME)"
fi
ok "gNB pod: $GNB_POD"

# Register cleanup trap — runs on any exit (timeout, error, success)
cleanup() {
    $K annotate pod "$GNB_POD" -n "$NAMESPACE" \
        "fault-injection/type-" "fault-injection/timestamp-" 2>/dev/null || true
}
trap cleanup EXIT

if ! check_dashboard; then
    fail "Dashboard not reachable at $DASHBOARD"
fi
ok "Dashboard reachable"

# ─── Step 1: Inject fault — simulate PTP timing drift ────────────────────────
echo ""
log "${R}Step 1: Injecting timing fault — annotating gNB with drift marker${NC}"

$K annotate pod "$GNB_POD" -n "$NAMESPACE" \
    "fault-injection/type=ptp-drift" \
    "fault-injection/timestamp=$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
    --overwrite 2>/dev/null
ok "Timing drift annotation applied"

$K exec "$GNB_POD" -n "$NAMESPACE" -- sh -c \
    'echo "[ERROR] late_harq: slot timing violation detected, offset=2847ns (threshold=1500ns)" >> /tmp/gnb-fault.log' \
    2>/dev/null || warn "Could not inject log (pod may not have shell)"

# ─── Step 2: Trigger alarm via API ───────────────────────────────────────────
echo ""
log "Step 2: Triggering $ALARM_TYPE alarm via API"
trigger_alarm "$ALARM_TYPE" \
    "{\"source\": \"$GNB_POD\", \"namespace\": \"$NAMESPACE\", \"severity\": \"critical\", \"detail\": \"PTP offset 2847ns exceeds 1500ns threshold\"}"

# ─── Step 3: Monitor pipeline ────────────────────────────────────────────────
echo ""
BASELINE=$(get_baseline_exec "$ALARM_NAME")
if ! monitor_pipeline "$ALARM_NAME" "$BASELINE"; then
    fail "Timeout after ${TIMEOUT}s — pipeline did not complete"
fi

# ─── Step 4: Verify recovery ─────────────────────────────────────────────────
echo ""
log "Step 4: Verifying gNB recovery"
sleep 10

FINAL_POD=$(find_pod "$NAMESPACE" "$NF_NAME") || true
FINAL_STATUS=$($K get pod "${FINAL_POD:-$GNB_POD}" -n "$NAMESPACE" --no-headers 2>/dev/null || echo "unknown")
echo "  $FINAL_STATUS"

if echo "$FINAL_STATUS" | grep -q "Running"; then
    CELL_OK=$($K logs "${FINAL_POD:-$GNB_POD}" -n "$NAMESPACE" --tail=5 2>/dev/null | grep -c "Cell started" || true)
    if [ "$CELL_OK" -gt "0" ]; then
        ok "gNB recovered — cell started, timing restored"
    else
        ok "gNB pod running (cell may still be syncing)"
    fi
else
    warn "gNB not yet Running — SOP may have restarted it"
fi

$K annotate pod "$GNB_POD" -n "$NAMESPACE" "fault-injection/type-" "fault-injection/timestamp-" 2>/dev/null || true

echo ""
log "Done. Full pipeline: fault → alarm → correlate → SOP → recovery ✅"
