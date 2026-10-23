#!/bin/bash
# Scenario 1 — manual restore (facilitator / stuck participant).
# Performs the same actions the SOP's Steps 3a and 4 describe, without the agents.
set -euo pipefail
# shellcheck source=_lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/_lib.sh" "$@"

banner "Scenario 1 — restore AMF"
require_cluster
step "Scaling AMF back to 1 replica"
kubectl scale deploy free5gc-amf-deployment -n "$NAMESPACE" --replicas=1
kubectl rollout status deploy free5gc-amf-deployment -n "$NAMESPACE" --timeout=180s
ok "AMF is back"
reattach_ue
verify_ue || true
show_active_alerts
echo "Alerts resolve on the next Prometheus evaluation (under a minute)."
