#!/bin/bash
# Scenario 3 — manual restore (facilitator / stuck participant).
# Mirrors SOP Step 3a.
set -euo pipefail
# shellcheck source=_lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/_lib.sh" "$@"

banner "Scenario 3 — restore PacketRusher"
require_cluster
reattach_ue
verify_ue || true
show_active_alerts
echo "free5gc_registration_unavailable resolves on the next AMF metric scrape (under a minute)."
