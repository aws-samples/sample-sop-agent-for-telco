#!/bin/bash
# =============================================================================
# IND321 - free5gc + packetrusher 5G Core functional/performance test suite.
# Mirrors docs/Free5GC-Testing-Guide.md. Run on the bastion after workloads
# are deployed. Non-fatal: each test reports PASS/FAIL and the suite continues.
# =============================================================================
set -uo pipefail

NAMESPACE="${NAMESPACE:-free5gc}"
VRF="${VRF:-vrf0000000003}"
UE_IF="${UE_IF:-val0000000003}"
PASS=0; FAIL=0

section() { echo ""; echo "=========================================="; echo "$1"; echo "=========================================="; }
check()   { if [ "$1" -eq 0 ]; then echo "  [PASS] $2"; PASS=$((PASS+1)); else echo "  [FAIL] $2"; FAIL=$((FAIL+1)); fi; }

section "Section 1: Pre-Test Verification"

echo "--> free5gc core pods"
kubectl get pods -n "${NAMESPACE}" | grep free5gc || true
FREE5GC_POD_COUNT=$(kubectl get pods -n "${NAMESPACE}" --no-headers 2>/dev/null | grep -c free5gc || true)
NOT_RUNNING=$(kubectl get pods -n "${NAMESPACE}" --no-headers 2>/dev/null | grep free5gc | grep -vcE 'Running|Completed' || true)
check "$([ "${FREE5GC_POD_COUNT}" -gt 0 ] && [ "${NOT_RUNNING}" -eq 0 ] && echo 0 || echo 1)" "Free5GC pods exist and are Running"

PACKETRUSHER_POD=$(kubectl get pods -n "${NAMESPACE}" -l app=packetrusher -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || true)
export PACKETRUSHER_POD
echo "--> PacketRusher pod: ${PACKETRUSHER_POD:-<none>}"
check "$([ -n "${PACKETRUSHER_POD}" ] && echo 0 || echo 1)" "PacketRusher pod discovered"

if [ -z "${PACKETRUSHER_POD}" ]; then
  echo "PacketRusher pod not found - aborting remaining tests."
  exit 1
fi

# Self-heal: if the UE has no 5G data interface yet, the PDU session hasn't come
# up. The usual cause is the stale subscriber slice; prune it and recreate the
# UE, then re-check. Makes the test run repeatable from a fresh deploy.
if ! kubectl exec -n "${NAMESPACE}" "${PACKETRUSHER_POD}" -- ip addr show "${UE_IF}" >/dev/null 2>&1; then
  echo "--> ${UE_IF} not present yet; running subscriber slice fix + recreating UE"
  SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../scripts/free5gc" && pwd)"
  if [ -f "${SCRIPT_DIR}/fix-subscriber-slice.sh" ]; then
    bash "${SCRIPT_DIR}/fix-subscriber-slice.sh" || true
  fi
  DEP=$(kubectl get deploy -n "${NAMESPACE}" -o name | grep packetrusher | head -1)
  if [ -n "${DEP}" ]; then
    kubectl -n "${NAMESPACE}" scale "${DEP}" --replicas=0 >/dev/null 2>&1
    sleep 15
    for p in $(kubectl get pods -n "${NAMESPACE}" -l app=packetrusher -o name); do kubectl delete -n "${NAMESPACE}" "$p" --grace-period=0 --force >/dev/null 2>&1 || true; done
    sleep 10
    kubectl -n "${NAMESPACE}" scale "${DEP}" --replicas=1 >/dev/null 2>&1
    sleep 80
    PACKETRUSHER_POD=$(kubectl get pods -n "${NAMESPACE}" -l app=packetrusher -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || true)
  fi
fi

echo "--> 5G interfaces on PacketRusher"
kubectl exec -n "${NAMESPACE}" "${PACKETRUSHER_POD}" -- ip addr show 2>/dev/null | grep -E "(n2|n3|${UE_IF})" || true

section "Section 2: Core Functional Tests"

echo "--> 2.1 UE 5G IP assignment"
kubectl exec -n "${NAMESPACE}" "${PACKETRUSHER_POD}" -- ip vrf exec "${VRF}" ip addr show "${UE_IF}"
check "$?" "UE has a 5G IP on ${UE_IF} (expect 10.63.0.x)"

echo "--> 2.2 5G data connectivity (ping 8.8.8.8 via ${VRF})"
kubectl exec -n "${NAMESPACE}" "${PACKETRUSHER_POD}" -- ip vrf exec "${VRF}" ping -c 4 8.8.8.8
check "$?" "5G data path reaches the internet"

echo "--> 2.3 DNS resolution via 5G interface"
kubectl exec -n "${NAMESPACE}" "${PACKETRUSHER_POD}" -- ip vrf exec "${VRF}" nslookup google.com
check "$?" "DNS resolves over the 5G path"

section "Section 3: Performance Testing (optional)"

if [ -n "${IPERF_IMAGE:-}" ]; then
  case "${IPERF_IMAGE}" in
    *:latest) echo "  [FAIL] IPERF_IMAGE must be immutable, not :latest"; FAIL=$((FAIL+1)) ;;
    *)
      echo "--> Deploying iperf3 server from ${IPERF_IMAGE}"
      kubectl run iperf-server -n "${NAMESPACE}" --image="${IPERF_IMAGE}" \
        --restart=Never --command -- iperf3 -s -p 5201
      kubectl expose pod iperf-server -n "${NAMESPACE}" --name=iperf-server-svc \
        --port=5201 --target-port=5201
      kubectl wait --for=condition=ready pod/iperf-server -n "${NAMESPACE}" --timeout=120s
      check "$?" "iperf3 server ready"
      SERVER_IP=$(kubectl get service iperf-server-svc -n "${NAMESPACE}" -o jsonpath='{.spec.clusterIP}')
      kubectl exec -n "${NAMESPACE}" "${PACKETRUSHER_POD}" -- \
        ip vrf exec "${VRF}" iperf3 -c "${SERVER_IP}" -p 5201 -t 10 -i 2
      check "$?" "5G throughput test completed"
      ;;
  esac
else
  echo "  [SKIP] Set IPERF_IMAGE to an immutable iperf3 image to run throughput testing."
fi

section "Section 4: Interface & UPF Validation"

UPF_POD=$(kubectl get pods -n "${NAMESPACE}" | grep upf | awk '{print $1}')
export UPF_POD
echo "--> UPF pod: ${UPF_POD:-<none>}"
kubectl exec -n "${NAMESPACE}" "${PACKETRUSHER_POD}" -- ip link show || true
if [ -n "${UPF_POD}" ]; then
  kubectl exec -n "${NAMESPACE}" "${UPF_POD}" -- ip -s link show n6 || true
fi

section "Results"
echo "PASS: ${PASS}   FAIL: ${FAIL}"
if [ "${FAIL}" -eq 0 ]; then
  echo "ALL TESTS PASSED"
  exit 0
fi
echo "SOME TESTS FAILED - see output above"
exit 1
