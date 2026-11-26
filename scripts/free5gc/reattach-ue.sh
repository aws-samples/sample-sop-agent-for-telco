#!/usr/bin/env bash
# Re-attach the simulated UE (PacketRusher gNB + UE) after a core NF restart.
#
# Used by sops/day2-remediate/core/free5gc-pod-crashloop.md Step 4. After the
# SMF restarts, the AMF still holds the UE's old SM context, so the first
# re-attach can fail with "Duplicated PDU session ID"; that attempt releases the
# stale context and a second one succeeds. Doing this in one script leaves the
# agent a single command and a single result line instead of a decision tree.
#
# PacketRusher is recreated with scale 0 -> 1, never pod delete or rollout
# restart: a new pod that starts while the old one still holds its Multus N2
# address fails with "ipvlan: address already in use".
#
# Prints one final line and exits:
#   0  "UE re-attached: <ip> (attempt N)"
#   1  "UE did not re-attach after N attempt(s): <reason>"
# Total run time stays under DEADLINE_SECONDS (default 110) so it fits the
# agent's command timeout.
set -uo pipefail

NAMESPACE="${NAMESPACE:-free5gc}"
DEPLOY="${DEPLOY:-packetrusher-packetrusher}"
SELECTOR="${SELECTOR:-app=packetrusher}"
AMF_DEPLOY="${AMF_DEPLOY:-free5gc-amf-deployment}"
MAX_ATTEMPTS="${MAX_ATTEMPTS:-2}"
DEADLINE_SECONDS="${DEADLINE_SECONDS:-110}"
START=$(date +%s)
ATTEMPT_START=${START}

remaining() { echo $(( DEADLINE_SECONDS - ($(date +%s) - START) )); }

recreate() {
  kubectl scale deploy "${DEPLOY}" -n "${NAMESPACE}" --replicas=0 >/dev/null
  kubectl wait --for=delete pod -l "${SELECTOR}" -n "${NAMESPACE}" --timeout="$(( $(remaining) > 5 ? $(remaining) / 3 : 5 ))s" >/dev/null 2>&1 || true
  kubectl scale deploy "${DEPLOY}" -n "${NAMESPACE}" --replicas=1 >/dev/null
  kubectl rollout status deploy "${DEPLOY}" -n "${NAMESPACE}" --timeout="$(( $(remaining) > 5 ? $(remaining) / 2 : 5 ))s" >/dev/null 2>&1 || true
}

ue_address() {  # prints the UE address once the PDU session is up
  local pod
  pod="$(kubectl get pods -n "${NAMESPACE}" -l "${SELECTOR}" -o jsonpath='{.items[0].metadata.name}' 2>/dev/null)"
  [ -n "${pod}" ] || return 1
  kubectl logs -n "${NAMESPACE}" "${pod}" -c packetrusher --tail=200 2>/dev/null \
    | grep -oE 'PDU address received: [0-9.]+' | tail -1 | awk '{print $4}'
}

stale_context() {  # the AMF rejected this attempt's session because of the old one
  local since=$(( $(date +%s) - ATTEMPT_START + 1 ))
  kubectl logs deploy/"${AMF_DEPLOY}" -n "${NAMESPACE}" --since="${since}s" 2>/dev/null \
    | grep -qE 'Duplicated PDU session ID|Release SmContext Failed'
}

reason="no PDU session"
attempt=0
while [ "${attempt}" -lt "${MAX_ATTEMPTS}" ] && [ "$(remaining)" -gt 15 ]; do
  attempt=$((attempt + 1))
  ATTEMPT_START=$(date +%s)
  echo "attempt ${attempt}: recreating ${DEPLOY} (scale 0 -> 1)"
  recreate
  while [ "$(remaining)" -gt 0 ]; do
    ip="$(ue_address)"
    if [ -n "${ip}" ]; then
      echo "UE re-attached: ${ip} (attempt ${attempt})"
      exit 0
    fi
    if stale_context; then
      reason="AMF reported a stale session (Duplicated PDU session ID)"
      echo "attempt ${attempt}: ${reason}; retrying"
      break
    fi
    sleep 5
  done
  [ "$(remaining)" -le 0 ] && reason="timed out after ${DEADLINE_SECONDS}s"
done
echo "UE did not re-attach after ${attempt} attempt(s): ${reason}"
exit 1
