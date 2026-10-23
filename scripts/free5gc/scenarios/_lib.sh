#!/bin/bash
# Shared helpers for the workshop fault-injection scenarios.
# Sourced by inject-*.sh / restore-*.sh; not meant to be run directly.
#
# Every scenario script:
#   * explains what it is about to do and what the participant should expect,
#   * asks for confirmation unless --yes is given,
#   * touches ONLY the free5gc namespace, with reversible kubectl operations,
#   * leaves the agents alone — detection and remediation are their job.

NAMESPACE="${FREE5GC_NAMESPACE:-free5gc}"
ANRA_NAMESPACE="${ANRA_NAMESPACE:-anra-system}"
MONITORING_NAMESPACE="${MONITORING_NAMESPACE:-monitoring}"

if [ -t 1 ]; then
  BOLD=$'\033[1m'; DIM=$'\033[2m'; RED=$'\033[31m'; GREEN=$'\033[32m'; YELLOW=$'\033[33m'; CYAN=$'\033[36m'; NC=$'\033[0m'
else
  BOLD=""; DIM=""; RED=""; GREEN=""; YELLOW=""; CYAN=""; NC=""
fi

banner() { printf '\n%s%s%s\n' "$BOLD" "$1" "$NC"; }
step()   { printf '%s==>%s %s\n' "$CYAN" "$NC" "$1"; }
ok()     { printf '%s  ✔%s %s\n' "$GREEN" "$NC" "$1"; }
warn()   { printf '%s  !%s %s\n' "$YELLOW" "$NC" "$1"; }
die()    { printf '%s  ✘ %s%s\n' "$RED" "$1" "$NC" >&2; exit 1; }

# confirm "<prompt>" — skipped when --yes/-y was passed to the calling script.
AUTO_YES=false
for arg in "$@"; do
  case "$arg" in --yes|-y) AUTO_YES=true ;; esac
done
confirm() {
  $AUTO_YES && return 0
  printf '%s%s [y/N] %s' "$BOLD" "$1" "$NC"
  read -r reply
  case "$reply" in y|Y|yes|YES) return 0 ;; *) echo "Aborted — nothing was changed."; exit 0 ;; esac
}

require_cluster() {
  kubectl get ns "$NAMESPACE" >/dev/null 2>&1 || die "namespace '$NAMESPACE' not found — is kubectl pointed at the workshop cluster?"
}

# Refuse to inject when the baseline is not healthy: a second fault on top of an
# unresolved one muddles what the agents correlate and what the participant sees.
require_healthy_baseline() {
  local bad
  bad=$(kubectl get deploy -n "$NAMESPACE" --no-headers 2>/dev/null | awk '$2!="1/1"{print $1}')
  [ -z "$bad" ] || die "baseline is not healthy — these deployments are not 1/1: $(echo "$bad" | tr '\n' ' '). Run the matching restore-*.sh (or wait for the agents) before injecting another fault."
}

show_active_alerts() {
  kubectl exec -n "$MONITORING_NAMESPACE" sts/alertmanager-kube-prometheus-stack-alertmanager -c alertmanager -- \
    wget -qO- 'http://localhost:9093/api/v2/alerts?active=true' 2>/dev/null |
    python3 -c 'import sys,json; a=[x["labels"]["alertname"] for x in json.load(sys.stdin) if x["labels"]["alertname"] not in ("Watchdog","InfoInhibitor")]; print("  active alerts:", a if a else "none")' 2>/dev/null || echo "  (could not query Alertmanager)"
}

# Recreate PacketRusher so the simulated UE registers again. PacketRusher only
# attaches at process start and owns a static Multus IP, so a plain restart is
# not enough; delete the pod and let the Deployment recreate it.
reattach_ue() {
  step "Recreating PacketRusher so the simulated UE re-registers"
  kubectl scale deploy packetrusher-packetrusher -n "$NAMESPACE" --replicas=1 >/dev/null
  kubectl delete pod -n "$NAMESPACE" -l app=packetrusher --ignore-not-found >/dev/null
  kubectl rollout status deploy packetrusher-packetrusher -n "$NAMESPACE" --timeout=120s >/dev/null
  ok "PacketRusher pod recreated"
}

verify_ue() {
  local pr
  pr=$(kubectl get pods -n "$NAMESPACE" -l app=packetrusher -o jsonpath='{.items[0].metadata.name}' 2>/dev/null) || true
  [ -n "$pr" ] || { warn "no PacketRusher pod found"; return 1; }
  sleep 20
  if kubectl exec -n "$NAMESPACE" "$pr" -c packetrusher -- ip vrf exec vrf0000000003 ping -c 2 -W 3 8.8.8.8 >/dev/null 2>&1; then
    ok "UE is registered and passing traffic (ping via the 5G user plane succeeded)"
  else
    warn "UE ping failed — registration may still be in progress; re-run verify in a minute: kubectl exec -n $NAMESPACE $pr -c packetrusher -- ip vrf exec vrf0000000003 ping -c 2 8.8.8.8"
    return 1
  fi
}

what_to_watch() {
  cat <<EOW

${BOLD}What to watch now${NC}
  1. Alertmanager (Grafana → Alerting, or):  kubectl -n $MONITORING_NAMESPACE exec sts/alertmanager-kube-prometheus-stack-alertmanager -c alertmanager -- wget -qO- 'http://localhost:9093/api/v2/alerts?active=true'
  2. Network Assurance Agent (ANRA) UI → Alarms, then Approvals. A pending approval bound to the SOP below should appear within about a minute.
  3. Open the SOP from the approval, read the Diagnose/Remediate/Verify steps, then click ${BOLD}Approve${NC}.
  4. Network Change Agent (ANDA): kubectl get deploymentplans -n anda-system -w   — the approved SOP becomes a DeploymentPlan and runs to Completed (~2 min).
  5. Alerts clear on their own once the network has recovered. Nothing to undo by hand.
${DIM}If you get stuck, scripts/free5gc/scenarios/restore-<scenario>.sh puts the network back without the agents.${NC}
EOW
}
