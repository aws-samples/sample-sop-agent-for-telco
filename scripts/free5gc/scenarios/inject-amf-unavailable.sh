#!/bin/bash
# Scenario 1 — Core network function unavailable (AMF)
#
# What this simulates
#   The AMF (Access and Mobility Management Function) is the 5G core's front
#   door for every phone: it terminates the N2 signalling link from the radio
#   network and owns each UE's registration. If the AMF process dies, is
#   mis-deployed, or is scaled to zero by a bad change, every UE loses
#   registration within seconds — a total outage for the cell site, even though
#   the rest of the core (SMF, UPF, databases) is perfectly healthy.
#
# What this script does
#   Scales free5gc-amf-deployment to 0 replicas in the free5gc namespace. That
#   is the Kubernetes equivalent of a crashed or decommissioned AMF: the
#   Deployment still exists, but no pod runs.
#
# What the agents should do
#   Prometheus rule free5gc_nf_unavailable fires (deployment has 0 available
#   replicas), followed by free5gc_registration_unavailable (the UE is gone).
#   The Network Assurance Agent correlates the two (the AMF is the root cause,
#   the lost registration is a consequence), binds the alarm to
#   sops/day2-remediate/core/free5gc-nf-unavailable.md and asks for approval.
#   Once approved, the Network Change Agent follows the SOP: confirms desired
#   replicas is 0 (not a crash), scales back to 1, waits for the AMF, recreates
#   PacketRusher so the UE re-registers, and verifies with the AMF log and a
#   ping through the 5G user plane.
#
# Usage:  inject-amf-unavailable.sh [--yes]
# Undo:   restore-amf-unavailable.sh   (only if you do not want the agents to do it)
set -euo pipefail
# shellcheck source=_lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/_lib.sh" "$@"

banner "Scenario 1 — AMF unavailable"
cat <<EOT
This will scale ${BOLD}free5gc-amf-deployment${NC} in namespace ${BOLD}$NAMESPACE${NC} to 0 replicas.
Simulates: the core's AMF going away — every connected UE loses registration.
Expected alarms: free5gc_nf_unavailable (root cause), free5gc_registration_unavailable (side-effect).
Bound SOP: sops/day2-remediate/core/free5gc-nf-unavailable.md
Reversible: yes (scale back to 1; the agents will do this after you approve).
EOT
require_cluster
require_healthy_baseline
confirm "Inject the fault now?"

step "Scaling AMF to 0 replicas"
kubectl scale deploy free5gc-amf-deployment -n "$NAMESPACE" --replicas=0
sleep 5
kubectl get deploy free5gc-amf-deployment -n "$NAMESPACE"
ok "Fault injected at $(date -u +%H:%M:%SZ)"
what_to_watch
