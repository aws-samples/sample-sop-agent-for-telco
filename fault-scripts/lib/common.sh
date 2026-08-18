#!/bin/bash
# =============================================================================
# fault-scripts/lib/common.sh — Shared helpers for fault injection scripts
#
# Source this file: source "$(dirname "$0")/lib/common.sh"
#
# All configuration via environment variables:
#   KUBECONFIG        — Path to kubeconfig (default: ~/.kube/config)
#   KUBECTL           — Path to kubectl binary (default: kubectl)
#   DASHBOARD_URL     — ANRA dashboard URL (REQUIRED, no default)
#   TIMEOUT           — Pipeline monitoring timeout in seconds (default: 300)
#   CORE_NAMESPACE    — Namespace for core NFs: AMF, SMF, UPF (default: open5gs)
#   RAN_NAMESPACE     — Namespace for RAN NFs: gNB, DU (default: srsran)
# =============================================================================

# ─── Config (override via env) ────────────────────────────────────────────────
export KUBECONFIG="${KUBECONFIG:-${HOME}/.kube/config}"
K="${KUBECTL:-kubectl}"
DASHBOARD="${DASHBOARD_URL:-}"
TIMEOUT="${TIMEOUT:-300}"
CORE_NAMESPACE="${CORE_NAMESPACE:-open5gs}"
RAN_NAMESPACE="${RAN_NAMESPACE:-srsran}"
BACKUP_DIR="${TMPDIR:-/tmp}"

# DASHBOARD_URL validated lazily in check_dashboard() and trigger_alarm()

# ─── Colors ───────────────────────────────────────────────────────────────────
R='\033[0;31m'
G='\033[0;32m'
Y='\033[1;33m'
C='\033[0;36m'
NC='\033[0m'
log()  { echo -e "${C}[$(date +%H:%M:%S)]${NC} $1" >&2; }
ok()   { echo -e "${G}  ✅ $1${NC}" >&2; }
warn() { echo -e "${Y}  ⚠️ $1${NC}" >&2; }
fail() { echo -e "${R}  ❌ $1${NC}" >&2; exit 1; }

# ─── Dynamic Pod Finder ───────────────────────────────────────────────────────
# Usage: find_pod <namespace> <nf_name>
#
# Tries multiple label conventions to find a pod:
#   1. app.kubernetes.io/name=<nf_name>          (Helm standard)
#   2. app=<nf_name>                             (simple)
#   3. app=<namespace>-<nf_name>                 (prefixed)
#   4. Pod name contains <nf_name>               (grep fallback)
#
# Returns: pod name (or empty string if not found)
find_pod() {
    local ns="$1"
    local nf="$2"
    local pod=""

    # Strategy 1: Helm standard label
    pod=$($K get pods -n "$ns" -l "app.kubernetes.io/name=$nf" --field-selector=status.phase=Running --no-headers -o custom-columns=":metadata.name" 2>/dev/null | grep -v "^$" | head -1)
    [ -n "$pod" ] && echo "$pod" && return 0

    # Strategy 2: Simple app label
    pod=$($K get pods -n "$ns" -l "app=$nf" --field-selector=status.phase=Running --no-headers -o custom-columns=":metadata.name" 2>/dev/null | grep -v "^$" | head -1)
    [ -n "$pod" ] && echo "$pod" && return 0

    # Strategy 3: Prefixed app label
    pod=$($K get pods -n "$ns" -l "app=${ns}-${nf}" --field-selector=status.phase=Running --no-headers -o custom-columns=":metadata.name" 2>/dev/null | grep -v "^$" | head -1)
    [ -n "$pod" ] && echo "$pod" && return 0

    # Strategy 4: Name-based grep (last resort, excludes sidecars/exporters/simulators)
    pod=$($K get pods -n "$ns" --field-selector=status.phase=Running --no-headers -o custom-columns=":metadata.name" 2>/dev/null | grep -F "$nf" | grep -v -E "ueransim|metrics|exporter|sidecar" | head -1)
    [ -n "$pod" ] && warn "Pod '$pod' found via name-grep fallback (Strategy 4)"
    [ -n "$pod" ] && echo "$pod" && return 0

    return 1
}

# ─── Dynamic ConfigMap Finder ─────────────────────────────────────────────────
# Usage: find_configmap <namespace> <nf_name>
find_configmap() {
    local ns="$1"
    local nf="$2"
    local cm=""

    cm=$($K get configmaps -n "$ns" -o custom-columns=":metadata.name" --no-headers 2>/dev/null | grep -i "$nf" | grep -v "kube" | head -1)
    [ -n "$cm" ] && echo "$cm" && return 0

    return 1
}

# ─── Dashboard Check ──────────────────────────────────────────────────────────
check_dashboard() {
    if [ -z "$DASHBOARD" ]; then
        echo "ERROR: DASHBOARD_URL env var is required" >&2
        return 1
    fi
    local status
    status=$(curl -sf --connect-timeout 5 --max-time 10 -o /dev/null -w "%{http_code}" "$DASHBOARD/health" 2>/dev/null || echo "000")
    if [ "$status" = "200" ]; then
        return 0
    fi
    return 1
}

# ─── Monitor Pipeline ─────────────────────────────────────────────────────────
# Usage: monitor_pipeline <alarm_type> <baseline_exec_count>
monitor_pipeline() {
    local alarm_type="$1"
    local baseline_exec="$2"
    local start last_stage elapsed activity latest_stage stage msg exec_count

    log "Monitoring autonomous pipeline (timeout: ${TIMEOUT}s)"
    echo ""
    start=$(date +%s)
    last_stage=""

    while true; do
        elapsed=$(( $(date +%s) - start ))
        if [ $elapsed -gt "$TIMEOUT" ]; then
            return 1  # timeout
        fi

        activity=$(curl -sf --connect-timeout 5 --max-time 10 "$DASHBOARD/api/activity?limit=5" 2>/dev/null || echo "{}")
        latest_stage=$(echo "$activity" | python3 -c "
import sys,json
data=json.load(sys.stdin)
items = data.get('activity', data) if isinstance(data, dict) else data
for a in (items[:1] if isinstance(items, list) else []):
    print(a.get('stage','') + '|' + a.get('message',''))
" 2>/dev/null || echo "")

        if [ -n "$latest_stage" ] && [ "$latest_stage" != "$last_stage" ]; then
            stage=$(echo "$latest_stage" | cut -d'|' -f1)
            msg=$(echo "$latest_stage" | cut -d'|' -f2)
            echo -e "  ${C}[+${elapsed}s]${NC} [${Y}${stage}${NC}] $msg"
            last_stage="$latest_stage"
        fi

        exec_count=$(curl -sf --connect-timeout 5 --max-time 10 "$DASHBOARD/api/executions" 2>/dev/null | python3 -c "
import sys,json
data=json.load(sys.stdin)
print(len([e for e in data.get('executions', []) if '$alarm_type' in e.get('alarm','')]))
" 2>/dev/null || echo "0")

        if [ "$exec_count" -gt "$baseline_exec" ]; then
            echo ""
            ok "SOP execution completed!"
            curl -sf --connect-timeout 5 --max-time 10 "$DASHBOARD/api/executions" 2>/dev/null | python3 -c "
import sys,json
data=json.load(sys.stdin)
for e in data.get('executions', []):
    if '$alarm_type' in e.get('alarm',''):
        print(f\"  Alarm:  {e.get('alarm')}\")
        print(f\"  Result: {e.get('result')}\")
        print(f\"  SOP:    {e.get('sop','').split('/')[-1]}\")
        print(f\"  Time:   {e.get('timestamp','')[:19]}\")
        break
" 2>/dev/null
            return 0
        fi

        sleep 5
    done
}

# ─── Get Baseline Execution Count ────────────────────────────────────────────
get_baseline_exec() {
    local alarm_type="$1"
    curl -sf --connect-timeout 5 --max-time 10 "$DASHBOARD/api/executions" 2>/dev/null | python3 -c "
import sys,json
data=json.load(sys.stdin)
print(len([e for e in data.get('executions', []) if '$alarm_type' in e.get('alarm','')]))
" 2>/dev/null || echo "0"
}

# ─── Trigger Alarm ────────────────────────────────────────────────────────────
trigger_alarm() {
    if [ -z "$DASHBOARD" ]; then
        fail "DASHBOARD_URL env var is required to trigger alarms"
    fi
    local alarm_type="$1"
    local payload="$2"
    local resp

    if resp=$(curl -s --connect-timeout 5 --max-time 10 -X POST "$DASHBOARD/api/alarms/trigger/$alarm_type" \
            -H "Content-Type: application/json" \
            -d "$payload" 2>/dev/null); then
        # API returns 200 even on error — check for error key in response
        if echo "$resp" | grep -q '"error"'; then
            fail "Alarm trigger failed: $resp"
        fi
        ok "Alarm injected: $resp"
    else
        fail "Failed to trigger alarm '$alarm_type' at $DASHBOARD (is the dashboard running?)"
    fi
}
