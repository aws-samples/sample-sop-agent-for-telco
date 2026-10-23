#!/bin/bash
# Scenario 2 — manual restore (facilitator / stuck participant).
# Mirrors SOP Step 3b (clear back-off) and Step 4 (re-attach UE).
set -euo pipefail
# shellcheck source=_lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/_lib.sh" "$@"

banner "Scenario 2 — restore SMF"
require_cluster
step "Restarting the SMF deployment to clear any CrashLoopBackOff"
kubectl rollout restart deploy free5gc-smf-deployment -n "$NAMESPACE"
kubectl rollout status deploy free5gc-smf-deployment -n "$NAMESPACE" --timeout=180s
ok "SMF is running with a fresh pod (restart counter reset)"
reattach_ue
verify_ue || true
show_active_alerts
echo "free5gc_pod_restarting clears once the 5-minute restart window has passed."
