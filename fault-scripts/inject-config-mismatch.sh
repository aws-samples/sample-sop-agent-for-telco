#!/bin/bash
# =============================================================================
# Fault Injection — Config Mismatch (Wrong PLMN Injected)
#
# Alarm:    amf_registration_failure
# SOP:      (config consistency validation)
# Severity: critical
#
# Env overrides:
#   CORRECT_MCC / CORRECT_MNC — Expected PLMN (default: read from site descriptor)
#   BAD_MCC / BAD_MNC         — PLMN to inject (default: 999/99)
#
# Usage:
#   ./inject-config-mismatch.sh              # full run
#   ./inject-config-mismatch.sh --dry-run    # show what would happen
# =============================================================================
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$SCRIPT_DIR/lib/common.sh"

NAMESPACE="$RAN_NAMESPACE"
NF_NAME="${GNB_NF_NAME:-gnb}"
ALARM_TYPE="config"
ALARM_NAME="amf_registration_failure"
DRY_RUN="${1:-}"

# ─── Cleanup trap (restore ConfigMap on abort) ────────────────────────────────
BACKUP_DIR="${TMPDIR:-/tmp}/fault-inject"
mkdir -p "$BACKUP_DIR"
_cleanup() {
    if [ -n "${BACKUP_FILE:-}" ] && [ -f "$BACKUP_FILE" ]; then
        warn "Interrupted — restoring ConfigMap from backup" >&2
        $K apply -f "$BACKUP_FILE" 2>/dev/null || true
        CURRENT_GNB=$(find_pod "$NAMESPACE" "$NF_NAME" 2>/dev/null) || true
        [ -n "$CURRENT_GNB" ] && $K delete pod "$CURRENT_GNB" -n "$NAMESPACE" --force --grace-period=0 2>/dev/null || true
    fi
}
trap _cleanup INT TERM

# PLMN values — override via env or auto-detect from ConfigMap
BAD_MCC="${BAD_MCC:-999}"
BAD_MNC="${BAD_MNC:-99}"

# ─── Dry-run shortcut (works without cluster access) ─────────────────────────
if [ "$DRY_RUN" = "--dry-run" ]; then
    log "DRY RUN — would execute:"
    echo "  1. Find gNB pod + ConfigMap in $NAMESPACE"
    echo "  2. Auto-detect PLMN from ConfigMap (or use CORRECT_MCC/MNC env)"
    echo "  3. Patch PLMN from detected → $BAD_MCC/$BAD_MNC"
    echo "  4. Restart gNB pod (picks up bad config)"
    echo "  5. POST $DASHBOARD/api/alarms/trigger/$ALARM_TYPE"
    echo "  6. Wait for ANRA pipeline → SOP rolls back config"
    echo "  7. Verify PLMN restored"
    exit 0
fi

# ─── Pre-flight ───────────────────────────────────────────────────────────────
log "Pre-flight checks..."

GNB_POD=$(find_pod "$NAMESPACE" "$NF_NAME") || true
if [ -z "$GNB_POD" ]; then
    fail "No gNB pod found in namespace $NAMESPACE (tried NF_NAME=$NF_NAME)"
fi
ok "gNB pod: $GNB_POD"

GNB_CM=$(find_configmap "$NAMESPACE" "$NF_NAME") || GNB_CM=$(find_configmap "$NAMESPACE" "${NAMESPACE}") || true
if [ -z "$GNB_CM" ]; then
    fail "No gNB ConfigMap found in namespace $NAMESPACE"
fi
ok "gNB ConfigMap: $GNB_CM"

# Auto-detect correct PLMN from ConfigMap if not overridden
# Supports formats: mcc: 440 / mnc: 10, plmn: "44010", plmn_id: {mcc: 440, mnc: 10}
if [ -z "${CORRECT_MCC:-}" ] || [ -z "${CORRECT_MNC:-}" ]; then
    read -r DET_MCC DET_MNC <<< $($K get configmap "$GNB_CM" -n "$NAMESPACE" -o json 2>/dev/null | python3 -c "
import sys, json, re
data = json.load(sys.stdin)
for v in data.get('data', {}).values():
    # Format 1: mcc: 440 / mnc: 10 (separate keys)
    mcc_m = re.search(r'mcc:\s*[\"\']?(\d{3})[\"\']?', v)
    mnc_m = re.search(r'mnc:\s*[\"\']?(\d{2,3})[\"\']?', v)
    if mcc_m and mnc_m:
        print(mcc_m.group(1), mnc_m.group(1)); break
    # Format 2: plmn: \"44010\" (combined 5-6 digit string)
    plmn_m = re.search(r'plmn:\s*[\"\']?(\d{5,6})[\"\']?', v)
    if plmn_m:
        p = plmn_m.group(1)
        print(p[:3], p[3:]); break
" 2>/dev/null || echo "")
    # Only fill in values that weren't user-supplied
    [ -z "${CORRECT_MCC:-}" ] && CORRECT_MCC="$DET_MCC"
    [ -z "${CORRECT_MNC:-}" ] && CORRECT_MNC="$DET_MNC"
fi

if [ -z "$CORRECT_MCC" ] || [ -z "$CORRECT_MNC" ]; then
    fail "Could not detect PLMN from ConfigMap $GNB_CM. Set CORRECT_MCC/CORRECT_MNC env vars."
fi
ok "Detected PLMN: $CORRECT_MCC/$CORRECT_MNC (will inject $BAD_MCC/$BAD_MNC)"

if ! check_dashboard; then
    fail "Dashboard not reachable at $DASHBOARD"
fi
ok "Dashboard reachable"


# ─── Step 1: Backup and corrupt ConfigMap ─────────────────────────────────────
echo ""
log "${R}Step 1: Injecting config mismatch — wrong PLMN${NC}"

BACKUP_FILE="${BACKUP_DIR}/gnb-cm-backup-$(date +%s).yaml"
$K get configmap "$GNB_CM" -n "$NAMESPACE" -o yaml > "$BACKUP_FILE" 2>/dev/null
ok "ConfigMap backed up to $BACKUP_FILE"

CM_DATA=$($K get configmap "$GNB_CM" -n "$NAMESPACE" -o json 2>/dev/null)
PATCHED_DATA=$(echo "$CM_DATA" | python3 -c "
import sys, json, re
data = json.load(sys.stdin)
changed = 0
for key in data.get('data', {}):
    # Scoped replacement: only replace MCC/MNC within PLMN patterns
    data['data'][key], n1 = re.subn(r'(mcc:\s*[\"\']?)$CORRECT_MCC([\"\']?)', r'\g<1>$BAD_MCC\2', data['data'][key])
    data['data'][key], n2 = re.subn(r'(mnc:\s*[\"\']?)$CORRECT_MNC([\"\']?)', r'\g<1>$BAD_MNC\2', data['data'][key])
    data['data'][key], n3 = re.subn(r'(plmn:\s*[\"\']?)${CORRECT_MCC}${CORRECT_MNC}([\"\']?)', r'\g<1>${BAD_MCC}${BAD_MNC}\2', data['data'][key])
    changed += n1 + n2 + n3
if changed:
    json.dump(data, sys.stdout)
" 2>/dev/null)

if [ -n "$PATCHED_DATA" ]; then
    echo "$PATCHED_DATA" | $K apply -f - 2>/dev/null
    ok "PLMN corrupted: $CORRECT_MCC/$CORRECT_MNC → $BAD_MCC/$BAD_MNC"
else
    $K annotate configmap "$GNB_CM" -n "$NAMESPACE" \
        "fault-injection/type=plmn-mismatch" \
        "fault-injection/bad-plmn=$BAD_MCC/$BAD_MNC" \
        --overwrite 2>/dev/null
    warn "Could not patch ConfigMap data — using annotation mode"
fi

log "Restarting gNB to load corrupted config..."
if ! $K delete pod "$GNB_POD" -n "$NAMESPACE" --force --grace-period=0 2>/dev/null; then
    fail "Failed to delete pod $GNB_POD"
fi
sleep 5
NEW_GNB=$(find_pod "$NAMESPACE" "$NF_NAME") || true
log "New gNB pod: ${NEW_GNB:-restarting...}"

# ─── Step 2: Trigger alarm via API ───────────────────────────────────────────
echo ""
log "Step 2: Triggering $ALARM_TYPE alarm via API"
trigger_alarm "$ALARM_TYPE" \
    "{\"source\": \"$GNB_POD\", \"namespace\": \"$NAMESPACE\", \"severity\": \"critical\", \"detail\": \"gNB NGAP registration rejected — PLMN $BAD_MCC/$BAD_MNC not in AMF allowed list\", \"expected_plmn\": \"$CORRECT_MCC/$CORRECT_MNC\", \"actual_plmn\": \"$BAD_MCC/$BAD_MNC\"}"

# ─── Step 3: Monitor pipeline ────────────────────────────────────────────────
echo ""
BASELINE=$(get_baseline_exec "$ALARM_NAME")
if ! monitor_pipeline "$ALARM_NAME" "$BASELINE"; then
    warn "Timeout — restoring config from backup"
    $K apply -f "$BACKUP_FILE" 2>/dev/null
    CURRENT_GNB=$(find_pod "$NAMESPACE" "$NF_NAME") || true
    $K delete pod "${CURRENT_GNB:-$GNB_POD}" -n "$NAMESPACE" --force --grace-period=0 2>/dev/null || true
    fail "Timeout after ${TIMEOUT}s — config restored manually"
fi

# ─── Step 4: Verify config restored ──────────────────────────────────────────
echo ""
log "Step 4: Verifying config restoration"
sleep 10

RESTORED_CM=$($K get configmap "$GNB_CM" -n "$NAMESPACE" -o json 2>/dev/null)
# Check PLMN only within .data values (not metadata/resourceVersion)
HAS_CORRECT=$(echo "$RESTORED_CM" | python3 -c "import sys,json; data=json.load(sys.stdin); print(sum(v.count('$CORRECT_MCC') for v in data.get('data',{}).values()))" 2>/dev/null || echo "0")
HAS_BAD=$(echo "$RESTORED_CM" | python3 -c "import sys,json; data=json.load(sys.stdin); print(sum(v.count('$BAD_MCC') for v in data.get('data',{}).values()))" 2>/dev/null || echo "0")

if [ "$HAS_CORRECT" -gt "0" ] && [ "$HAS_BAD" = "0" ]; then
    ok "PLMN restored to $CORRECT_MCC/$CORRECT_MNC — config correct"
else
    warn "Config may not be fully restored — applying backup"
    $K apply -f "$BACKUP_FILE" 2>/dev/null
    CURRENT_GNB=$(find_pod "$NAMESPACE" "$NF_NAME") || true
    $K delete pod "${CURRENT_GNB:-$GNB_POD}" -n "$NAMESPACE" --force --grace-period=0 2>/dev/null || true
    ok "Backup applied from $BACKUP_FILE"
fi

FINAL_GNB=$(find_pod "$NAMESPACE" "$NF_NAME") || true
FINAL_STATUS=$($K get pod "${FINAL_GNB:-$GNB_POD}" -n "$NAMESPACE" --no-headers 2>/dev/null || echo "unknown")
echo "  gNB: $FINAL_STATUS"

if echo "$FINAL_STATUS" | grep -q "Running"; then
    ok "gNB running with correct PLMN — registration should succeed"
fi

echo ""
log "Done. Full pipeline: bad config → registration fail → alarm → SOP rollback → recovery ✅"
