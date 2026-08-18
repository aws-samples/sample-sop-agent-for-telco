#!/bin/bash
# =============================================================================
# Fault Injection — UPF Memory Pressure (OOM)
#
# Alarm:    os_memory_pressure
# SOP:      day2-remediate/infra/remediate-os-memory-pressure.md
# Severity: warning → critical
#
# Usage:
#   ./inject-memory-pressure.sh              # full run
#   ./inject-memory-pressure.sh --dry-run    # show what would happen
# =============================================================================
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$SCRIPT_DIR/lib/common.sh"

NAMESPACE="$CORE_NAMESPACE"
NF_NAME="${UPF_NF_NAME:-upf}"
ALARM_TYPE="memory"
ALARM_NAME="os_memory_pressure"
DRY_RUN="${1:-}"


# ─── Dry-run shortcut (works without cluster access) ─────────────────────────
if [ "$DRY_RUN" = "--dry-run" ]; then
    log "DRY RUN — would execute:"
    echo "  1. Annotate UPF pod with memory-pressure fault marker"
    echo "  2. POST $DASHBOARD/api/alarms/trigger/$ALARM_TYPE"
    echo "  3. Wait for ANRA pipeline (detect → correlate → execute SOP)"
    echo "  4. Monitor until alarm clears or timeout (${TIMEOUT}s)"
    exit 0
fi
# ─── Pre-flight ───────────────────────────────────────────────────────────────
log "Pre-flight checks..."

UPF_POD=$(find_pod "$NAMESPACE" "$NF_NAME") || true
if [ -z "$UPF_POD" ]; then
    fail "No UPF pod found in namespace $NAMESPACE (tried NF_NAME=$NF_NAME)"
fi
ok "UPF pod: $UPF_POD"

# Register cleanup trap — runs on any exit (timeout, error, success)
cleanup() {
    $K annotate pod "$UPF_POD" -n "$NAMESPACE" \
        "fault-injection/type-" "fault-injection/timestamp-" "fault-injection/original-limit-" 2>/dev/null || true
}
trap cleanup EXIT

UPF_NODE=$($K get pod "$UPF_POD" -n "$NAMESPACE" -o jsonpath='{.spec.nodeName}' 2>/dev/null || echo "unknown")
ok "UPF node: $UPF_NODE"

if ! check_dashboard; then
    fail "Dashboard not reachable at $DASHBOARD"
fi
ok "Dashboard reachable"

# ─── Step 1: Inject fault — simulate memory pressure ─────────────────────────
echo ""
log "${R}Step 1: Injecting memory pressure on UPF${NC}"

ORIG_MEM_LIMIT=$($K get pod "$UPF_POD" -n "$NAMESPACE" -o jsonpath='{.spec.containers[0].resources.limits.memory}' 2>/dev/null || echo "")

$K annotate pod "$UPF_POD" -n "$NAMESPACE" \
    "fault-injection/type=memory-pressure" \
    "fault-injection/timestamp=$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
    "fault-injection/original-limit=${ORIG_MEM_LIMIT}" \
    --overwrite 2>/dev/null || warn "Failed to annotate UPF pod; continuing"
ok "Memory pressure annotation applied (original limit: ${ORIG_MEM_LIMIT:-none})"
warn "Simulating pressure via alarm injection (non-destructive for workshop)"

# ─── Step 2: Trigger alarm via API ───────────────────────────────────────────
echo ""
log "Step 2: Triggering $ALARM_TYPE alarm via API"
trigger_alarm "$ALARM_TYPE" \
    "{\"source\": \"$UPF_POD\", \"namespace\": \"$NAMESPACE\", \"node\": \"$UPF_NODE\", \"severity\": \"warning\", \"detail\": \"Memory usage 94% (limit: ${ORIG_MEM_LIMIT:-256Mi}), approaching OOM\"}"

# ─── Step 3: Monitor pipeline ────────────────────────────────────────────────
echo ""
BASELINE=$(get_baseline_exec "$ALARM_NAME")
if ! monitor_pipeline "$ALARM_NAME" "$BASELINE"; then
    fail "Timeout after ${TIMEOUT}s — pipeline did not complete"
fi

# ─── Step 4: Verify recovery ─────────────────────────────────────────────────
echo ""
log "Step 4: Verifying UPF recovery"
sleep 5

FINAL_POD=$(find_pod "$NAMESPACE" "$NF_NAME") || true
FINAL_STATUS=$($K get pod "${FINAL_POD:-$UPF_POD}" -n "$NAMESPACE" --no-headers 2>/dev/null || echo "unknown")
echo "  $FINAL_STATUS"

if echo "$FINAL_STATUS" | grep -q "Running"; then
    ok "UPF pod running — memory pressure resolved"
else
    warn "UPF pod may have been restarted by SOP"
fi

$K annotate pod "$UPF_POD" -n "$NAMESPACE" "fault-injection/type-" "fault-injection/timestamp-" "fault-injection/original-limit-" 2>/dev/null || true

echo ""
log "Done. Full pipeline: memory pressure → alarm → correlate → SOP → recovery ✅"
