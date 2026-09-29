#!/bin/bash
# =============================================================================
# IND321 - Deploy free5gc core + packetrusher and bring up a working E2E 5G call.
#
# This script is IDEMPOTENT and encodes every lesson learned during bring-up:
#   1. gtp5g must be built + loaded on every worker node BEFORE the UPF starts
#      (see scripts/install-gtp5g.sh). We verify it here and fail fast if missing.
#   2. free5gc is installed first, then packetrusher (which waits for the AMF).
#   3. The UPF/SMF must come up in order once gtp5g is present; a plain rollout
#      can leave them crashlooped, so we reconcile them with a clean restart.
#   4. The subscriber provisioning leaves a stale factory S-NSSAI (sst1/sd010203)
#      alongside the real slice (sst1/sd112233). With both present the PDU session
#      fails with "DNN not supported or not subscribed in the slice", so we prune
#      the stale slice (scripts/fix-subscriber-slice.sh).
#   5. packetrusher + UPF own singleton static Multus IPs, so they must be
#      recreated via scale 0->1 (never a rolling restart) to avoid IP contention.
#
# Run on the bastion after 02-configure-cluster.sh.
# =============================================================================
set -euo pipefail

NAMESPACE="${NAMESPACE:-free5gc}"
STACK_NAME="${STACK_NAME:-telco-workshop-v3}"
CLUSTER_NAME="${CLUSTER_NAME:-eks-${STACK_NAME}}"
AWS_DEFAULT_REGION="${AWS_DEFAULT_REGION:-us-west-2}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
CHARTS_DIR="${CHARTS_DIR:-${REPO_ROOT}/helm-charts/free5gc-bundle}"
FREE5GC_CHART="${FREE5GC_CHART:-${CHARTS_DIR}/free5gc-0.0.2.tgz}"
PACKETRUSHER_CHART="${PACKETRUSHER_CHART:-${CHARTS_DIR}/packetrusher-0.0.3.tgz}"
STALE_SD="${STALE_SD:-010203}"
UE_IMSI="${UE_IMSI:-imsi-208930000000003}"

export AWS_DEFAULT_REGION
aws eks update-kubeconfig --region "${AWS_DEFAULT_REGION}" --name "${CLUSTER_NAME}" >/dev/null

krestart_recreate() {  # $1 = deployment name  (clean scale 0 -> 1 for singleton Multus pods)
  local dep="$1"
  kubectl -n "${NAMESPACE}" scale deploy "${dep}" --replicas=0 >/dev/null 2>&1 || return 0
  sleep 15
  for p in $(kubectl get pods -n "${NAMESPACE}" -o name | grep "${dep}" 2>/dev/null); do
    kubectl delete -n "${NAMESPACE}" "$p" --grace-period=0 --force >/dev/null 2>&1 || true
  done
  sleep 10
  kubectl -n "${NAMESPACE}" scale deploy "${dep}" --replicas=1 >/dev/null 2>&1 || true
}

kubectl create namespace "${NAMESPACE}" --dry-run=client -o yaml | kubectl apply -f -

# ---- 0. Verify gtp5g is loaded on all worker nodes --------------------------
# The GTP5G module is built + loaded at boot by the node user-data (see the CFN
# launch template) and can be (re)installed with scripts/install-gtp5g.sh.
#
# We verify it node-side via a short-lived privileged pod that reads the host's
# loaded modules. The bastion uses SSM for installation in step 02; this pod is
# an independent Kubernetes-side verification. Set SKIP_GTP5G_CHECK=1 to skip.
if [ "${SKIP_GTP5G_CHECK:-0}" = "1" ]; then
  echo "==> Skipping gtp5g verification (SKIP_GTP5G_CHECK=1)"
else
  echo "==> Verifying gtp5g kernel module on worker nodes (via a privileged check pod)"
  NODES=$(kubectl get nodes -o jsonpath='{.items[*].metadata.name}')
  MISSING=0
  for node in ${NODES}; do
    POD="gtp5g-check-$(echo "${node}" | tr '.' '-' | cut -c1-40)"
    kubectl run "${POD}" -n "${NAMESPACE}" --restart=Never --image=busybox:1.36 \
      --overrides="{\"spec\":{\"nodeName\":\"${node}\",\"hostPID\":true,\"containers\":[{\"name\":\"c\",\"image\":\"busybox:1.36\",\"command\":[\"sh\",\"-c\",\"cat /host/proc/modules | grep -q gtp5g && echo LOADED || echo MISSING\"],\"securityContext\":{\"privileged\":true},\"volumeMounts\":[{\"name\":\"host\",\"mountPath\":\"/host\"}]}],\"volumes\":[{\"name\":\"host\",\"hostPath\":{\"path\":\"/\"}}]}}" \
      >/dev/null 2>&1 || true
    kubectl wait --for=jsonpath='{.status.phase}'=Succeeded pod/"${POD}" -n "${NAMESPACE}" --timeout=60s >/dev/null 2>&1 || true
    RES=$(kubectl logs "${POD}" -n "${NAMESPACE}" 2>/dev/null | tr -d '[:space:]')
    kubectl delete pod "${POD}" -n "${NAMESPACE}" --grace-period=0 --force >/dev/null 2>&1 || true
    echo "   node ${node}: ${RES:-UNKNOWN}"
    [ "${RES}" != "LOADED" ] && MISSING=1
  done
  if [ "${MISSING}" -ne 0 ]; then
    echo "ERROR: gtp5g is not confirmed loaded on all nodes. Run scripts/install-gtp5g.sh"
    echo "       on each worker node, or re-run with SKIP_GTP5G_CHECK=1 if you have"
    echo "       verified it out-of-band, then re-run this script."
    exit 1
  fi
fi

# ---- 1. Install free5gc core ------------------------------------------------
# The chart ships a PodMonitor (monitoring.coreos.com/v1). If the Prometheus
# Operator CRDs are not present (i.e. 04-deploy-monitoring.sh has not run yet),
# disable the PodMonitor so the install does not fail. Metrics are still exported
# by the NF pods; the PodMonitor can be added later by installing monitoring.
PODMON_ARGS=()
if ! kubectl get crd podmonitors.monitoring.coreos.com >/dev/null 2>&1; then
  echo "   (PodMonitor CRD absent -> installing free5gc with metrics.podMonitor.enable=false)"
  PODMON_ARGS=(--set metrics.podMonitor.enable=false)
fi

echo "==> helm install/upgrade free5gc"
helm upgrade --install free5gc "${FREE5GC_CHART}" -n "${NAMESPACE}" "${PODMON_ARGS[@]}"

echo "==> Waiting for the free5gc control plane to settle"
sleep 60
kubectl -n "${NAMESPACE}" wait --for=condition=available deploy/free5gc-amf-deployment --timeout=300s 2>/dev/null || true

# ---- 2. Reconcile UPF then SMF (order matters; clean recreate) --------------
echo "==> Reconciling UPF (needs gtp5g) then SMF (needs UPF/N4)"
if kubectl get pods -n "${NAMESPACE}" | grep -qE 'upf.*(CrashLoopBackOff|Error|Init)'; then
  krestart_recreate free5gc-upf-deployment
  sleep 75
fi
if kubectl get pods -n "${NAMESPACE}" | grep -qE 'smf.*(CrashLoopBackOff|Error|Init)'; then
  kubectl -n "${NAMESPACE}" rollout restart deploy free5gc-smf-deployment
  sleep 45
fi

# ---- 3. Prune the stale factory S-NSSAI from the subscriber -----------------
echo "==> Pruning stale S-NSSAI (sd=${STALE_SD}) from provisioned subscriber data"
bash "${SCRIPT_DIR}/fix-subscriber-slice.sh"

# ---- 4. Install packetrusher and recreate cleanly so it re-registers --------
echo "==> helm install/upgrade packetrusher"
helm upgrade --install packetrusher "${PACKETRUSHER_CHART}" -n "${NAMESPACE}"
sleep 30
echo "==> Recreating packetrusher so the UE registers against the clean subscriber"
krestart_recreate packetrusher-packetrusher
sleep 80

# ---- 5. Report --------------------------------------------------------------
echo "==> Final pod state"
kubectl get pods -n "${NAMESPACE}" -o wide
echo ""
echo "==> packetrusher PDU session status"
PR=$(kubectl get pods -n "${NAMESPACE}" -l app=packetrusher -o jsonpath='{.items[0].metadata.name}' 2>/dev/null)
if [ -n "${PR}" ]; then
  kubectl logs -n "${NAMESPACE}" "${PR}" --tail=20 2>/dev/null | \
    grep -Ei "pdu|address received|val0000|5GMM" || true
fi
echo ""
echo "Done. Run tests/run-tests.sh to validate the E2E 5G call."
