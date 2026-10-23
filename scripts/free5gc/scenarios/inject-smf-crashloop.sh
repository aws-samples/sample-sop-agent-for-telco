#!/bin/bash
# Scenario 2 — Network function repeatedly restarting (SMF)
#
# What this simulates
#   The SMF (Session Management Function) sets up and owns every data session
#   (PDU session): it picks the UPF, assigns the UE's IP address and programs
#   the user-plane rules over the N4/PFCP interface. A flapping SMF is one of
#   the most common real-world core faults — out-of-memory kills, a bad
#   configuration pushed by an upgrade, or a node under pressure. Each restart
#   drops the UE's data session even though the phone stays registered, and
#   Kubernetes' exponential back-off makes the recovery slower every time.
#
# What this script does
#   Kills PID 1 inside the running SMF container three times, 20 seconds apart.
#   Each kill makes the container exit (code 137) and Kubernetes restarts it,
#   so the pod's restart counter climbs past the alert threshold. No
#   configuration or image is changed — the fault is purely "something keeps
#   killing the process", which is exactly how an OOM or a node problem looks.
#
# What the agents should do
#   Prometheus rule free5gc_pod_restarting fires (more than two restarts in five
#   minutes). The Network Assurance Agent binds it to
#   sops/day2-remediate/core/free5gc-pod-crashloop.md and asks for approval.
#   The Network Change Agent then reads the previous container's exit reason
#   and logs, classifies the cause (here: external kill — abrupt log end, exit
#   137, no OOMKilled flag), clears the back-off with a rollout restart, checks
#   node memory, recreates PacketRusher so the PDU session comes back, and
#   confirms the restart count has stopped climbing.
#
# Note: the alert needs the 5-minute restart window to roll past the last
# restart before it clears, so expect it to stay active for a few minutes
# after the fix even when everything is healthy.
#
# Usage:  inject-smf-crashloop.sh [--yes]
# Undo:   restore-smf-crashloop.sh
set -euo pipefail
# shellcheck source=_lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/_lib.sh" "$@"

banner "Scenario 2 — SMF repeatedly restarting"
cat <<EOT
This will kill the main process of the ${BOLD}free5gc-smf-deployment${NC} container 3 times, 20s apart, in namespace ${BOLD}$NAMESPACE${NC}.
Simulates: a flapping SMF (OOM kills / node pressure) — data sessions drop on every restart.
Expected alarm: free5gc_pod_restarting (warning).
Bound SOP: sops/day2-remediate/core/free5gc-pod-crashloop.md
Reversible: yes — nothing is changed; the agents clear the back-off and re-attach the UE.
EOT
require_cluster
require_healthy_baseline
confirm "Inject the fault now?"

for i in 1 2 3; do
  pod=$(kubectl get pods -n "$NAMESPACE" -l epc-mode=smf -o jsonpath='{.items[0].metadata.name}')
  step "Kill $i/3: terminating PID 1 in $pod (container smf)"
  kubectl exec -n "$NAMESPACE" "$pod" -c smf -- kill 1 2>/dev/null || true
  sleep 20
done
kubectl get pods -n "$NAMESPACE" -l epc-mode=smf
ok "Fault injected at $(date -u +%H:%M:%SZ) — restart count should read 3 (or more)"
what_to_watch
