#!/bin/bash
# Scenario 3 — No UE registered (radio side lost)
#
# What this simulates
#   In this lab the whole radio access network is one PacketRusher pod: a
#   simulated gNB (cell tower) with one attached UE (phone). When the gNB
#   disappears — fibre cut to the site, cell-site power loss, a gNB software
#   crash, or a configuration drift such as a PLMN/TAC mismatch that makes the
#   AMF reject the gNB — the core stays healthy but serves nobody. From the
#   core's point of view the only symptom is "registered UEs dropped to zero",
#   which is why operators alarm on that metric rather than on the gNB itself.
#
# What this script does
#   Scales packetrusher-packetrusher to 0 replicas. The AMF's registered-UE
#   gauge (free5gc_amf_business_ue_gmm_state_count{gmm_state="Registered"})
#   drops to 0 while every core NF remains 1/1.
#
# What the agents should do
#   Prometheus rule free5gc_registration_unavailable fires. The Network
#   Assurance Agent checks that no core NF alarm is active (so this is the root
#   cause, not a consequence), binds it to
#   sops/day2-remediate/core/free5gc-registration-unavailable.md and asks for
#   approval. The Network Change Agent then reads the AMF and PacketRusher logs,
#   determines the gNB is simply gone (no reject, no PLMN mismatch, no SCTP
#   errors), restores PacketRusher (scale to 1, recreate), and verifies
#   "Registration accept" in the AMF log, the UE's 10.63.x.x address and a ping
#   through the 5G user plane.
#
# Usage:  inject-registration-unavailable.sh [--yes]
# Undo:   restore-registration-unavailable.sh
set -euo pipefail
# shellcheck source=_lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/_lib.sh" "$@"

banner "Scenario 3 — UE registration lost"
cat <<EOT
This will scale ${BOLD}packetrusher-packetrusher${NC} (simulated gNB + UE) in namespace ${BOLD}$NAMESPACE${NC} to 0 replicas.
Simulates: the radio site going away — the core is healthy but has no registered UE.
Expected alarm: free5gc_registration_unavailable (critical). No core NF alarm should fire.
Bound SOP: sops/day2-remediate/core/free5gc-registration-unavailable.md
Reversible: yes (scale back to 1; the agents will do this after you approve).
EOT
require_cluster
require_healthy_baseline
confirm "Inject the fault now?"

step "Scaling PacketRusher to 0 replicas"
kubectl scale deploy packetrusher-packetrusher -n "$NAMESPACE" --replicas=0
sleep 5
kubectl get deploy packetrusher-packetrusher -n "$NAMESPACE"
ok "Fault injected at $(date -u +%H:%M:%SZ)"
what_to_watch
