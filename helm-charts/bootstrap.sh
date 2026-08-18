#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# ANO Platform Bootstrap
# ---------------------------------------------------------------------------
# Installs the control plane (ArgoCD, ANPA, ANDA) on the management cluster
# and ANRA on workload clusters.
#
# This script runs ONCE during initial platform standup.
# After bootstrap, agents manage their own lifecycle:
#   - ANPA/ANDA: upgraded via `helm upgrade` with approval
#   - ANRA: self-updating from ECR (see selfUpdate in values.yaml)
#
# Usage:
#   ./bootstrap.sh --mgmt-context <ctx> --values <path> [options]
#
# Options:
#   --mgmt-context     Kubeconfig context for management cluster (required)
#   --workload-context Kubeconfig context for workload cluster(s), comma-separated
#   --values           Path to site-specific values file (required)
#   --registry         ECR registry URI (e.g. 123456.dkr.ecr.us-west-2.amazonaws.com)
#   --skip-argocd      Skip ArgoCD installation (already installed)
#   --skip-anpa        Skip ANPA (provisioning not needed)
#   --skip-anda        Skip ANDA (deployment agent not needed)
#   --skip-anra        Skip ANRA (remediation not needed yet)
#   --dry-run          Print commands without executing
#   --help             Show this help
# ---------------------------------------------------------------------------
set -euo pipefail

# --- Defaults ---
HELM_REPO="oci://public.ecr.aws/eks-hybrid-telco/helm"
CHART_VERSION="0.2.0"
ARGOCD_CHART_VERSION="7.3.11"  # pin to a tested version

ARGOCD_NAMESPACE="argocd"
ANRA_SYSTEM_NS="anra-system"
SKIP_ARGOCD=false
SKIP_ANPA=false
SKIP_ANDA=false
SKIP_ANRA=false
DRY_RUN=false
MGMT_CONTEXT=""
WORKLOAD_CONTEXTS=""
VALUES_FILE=""
REGISTRY=""

# --- Save original kubeconfig context for cleanup ---
ORIGINAL_CONTEXT="$(kubectl config current-context 2>/dev/null || echo "")"

cleanup() {
  local exit_code=$?
  if [ -n "${ORIGINAL_CONTEXT}" ] && [ "${DRY_RUN}" = false ]; then
    kubectl config use-context "${ORIGINAL_CONTEXT}" >/dev/null 2>&1 || true
  fi
  if [ ${exit_code} -ne 0 ]; then
    echo "$(date -u +%FT%TZ) [bootstrap] ERROR: Bootstrap failed (exit ${exit_code}). Restored kubeconfig context." >&2
  fi
  exit ${exit_code}
}
trap cleanup EXIT INT TERM

# --- Parse args ---
while [[ $# -gt 0 ]]; do
  case $1 in
    --mgmt-context)     MGMT_CONTEXT="$2"; shift 2 ;;
    --workload-context) WORKLOAD_CONTEXTS="$2"; shift 2 ;;
    --values)           VALUES_FILE="$2"; shift 2 ;;
    --registry)         REGISTRY="$2"; shift 2 ;;
    --skip-argocd)      SKIP_ARGOCD=true; shift ;;
    --skip-anpa)        SKIP_ANPA=true; shift ;;
    --skip-anda)        SKIP_ANDA=true; shift ;;
    --skip-anra)        SKIP_ANRA=true; shift ;;
    --dry-run)          DRY_RUN=true; shift ;;
    --help)
      head -30 "$0" | grep '^#' | sed 's/^# \?//'
      exit 0
      ;;
    *) echo "Unknown option: $1"; exit 1 ;;
  esac
done

# --- Validation ---
if [ -z "${MGMT_CONTEXT}" ]; then
  echo "ERROR: --mgmt-context is required"
  exit 1
fi
if [ -z "${VALUES_FILE}" ] || [ ! -f "${VALUES_FILE}" ]; then
  echo "ERROR: --values must point to an existing file"
  exit 1
fi

# --- Helpers ---
log()  { echo "$(date -u +%FT%TZ) [bootstrap] $*"; }
run()  {
  if [ "${DRY_RUN}" = true ]; then
    echo "  [dry-run] $*"
  else
    "$@"
  fi
}

# ---------------------------------------------------------------------------
# Phase 1: Management Cluster — Shared CRDs + ArgoCD
# ---------------------------------------------------------------------------
log "=== Phase 1: Management Cluster Setup ==="
log "Context: ${MGMT_CONTEXT}"
run kubectl config use-context "${MGMT_CONTEXT}"

# 1a. Shared CRDs (always installed first)
log "Installing anra-common CRDs..."
run helm upgrade --install anra-common "${HELM_REPO}/anra-common" \
  --version "${CHART_VERSION}" \
  --namespace "${ANRA_SYSTEM_NS}" \
  --create-namespace \
  --wait

# 1b. ArgoCD (for NF deployment, NOT for agent LCM)
if [ "${SKIP_ARGOCD}" = false ]; then
  log "Installing ArgoCD..."
  run helm repo add argo https://argoproj.github.io/argo-helm 2>/dev/null || true
  run helm repo update argo
  run helm upgrade --install argocd argo/argo-cd \
    --version "${ARGOCD_CHART_VERSION}" \
    --namespace "${ARGOCD_NAMESPACE}" \
    --create-namespace \
    --set server.service.type=ClusterIP \
    --set configs.params."server\.insecure"=true \
    --wait --timeout 5m
  log "ArgoCD installed. Access: kubectl port-forward svc/argocd-server -n ${ARGOCD_NAMESPACE} 8080:443"
else
  log "Skipping ArgoCD (--skip-argocd)"
fi

# ---------------------------------------------------------------------------
# Phase 2: Management Cluster — ANPA (Day 0)
# ---------------------------------------------------------------------------
if [ "${SKIP_ANPA}" = false ]; then
  log "=== Phase 2: Installing ANPA (Day 0 Provisioning Agent) ==="
  ANPA_ARGS=(
    --version "${CHART_VERSION}"
    --namespace anpa-system
    --create-namespace
    --values "${VALUES_FILE}"
    --wait --timeout 3m
  )
  [ -n "${REGISTRY}" ] && ANPA_ARGS+=(--set "image.repository=${REGISTRY}/ano-platform")

  run helm upgrade --install anpa "${HELM_REPO}/anpa" "${ANPA_ARGS[@]}"
  log "ANPA installed."
else
  log "Skipping ANPA (--skip-anpa)"
fi

# ---------------------------------------------------------------------------
# Phase 3: Management Cluster — ANDA (Day 1)
# ---------------------------------------------------------------------------
if [ "${SKIP_ANDA}" = false ]; then
  log "=== Phase 3: Installing ANDA (Day 1 Deployment Agent) ==="
  ANDA_ARGS=(
    --version "${CHART_VERSION}"
    --namespace anda-system
    --create-namespace
    --values "${VALUES_FILE}"
    --wait --timeout 3m
  )
  [ -n "${REGISTRY}" ] && ANDA_ARGS+=(--set "image.repository=${REGISTRY}/ano-platform")

  run helm upgrade --install anda "${HELM_REPO}/anda" "${ANDA_ARGS[@]}"
  log "ANDA installed."
else
  log "Skipping ANDA (--skip-anda)"
fi

# ---------------------------------------------------------------------------
# Phase 4: Workload Clusters — ANRA (Day 2)
# ---------------------------------------------------------------------------
if [ "${SKIP_ANRA}" = false ] && [ -n "${WORKLOAD_CONTEXTS}" ]; then
  log "=== Phase 4: Installing ANRA on Workload Clusters ==="

  IFS=',' read -ra CONTEXTS <<< "${WORKLOAD_CONTEXTS}"
  for CTX in "${CONTEXTS[@]}"; do
    CTX=$(echo "${CTX}" | xargs)  # trim whitespace
    log "  Cluster: ${CTX}"
    run kubectl config use-context "${CTX}"

    # Install shared CRDs on workload cluster
    run helm upgrade --install anra-common "${HELM_REPO}/anra-common" \
      --version "${CHART_VERSION}" \
      --namespace "${ANRA_SYSTEM_NS}" \
      --create-namespace \
      --wait

    # Install ANRA with self-update enabled
    ANRA_ARGS=(
      --version "${CHART_VERSION}"
      --namespace "${ANRA_SYSTEM_NS}"
      --create-namespace
      --values "${VALUES_FILE}"
      --set selfUpdate.enabled=true
      --wait --timeout 3m
    )
    [ -n "${REGISTRY}" ] && ANRA_ARGS+=(--set "image.repository=${REGISTRY}/ano-platform")

    run helm upgrade --install anra "${HELM_REPO}/anra" "${ANRA_ARGS[@]}"
    log "  ANRA installed on ${CTX}"
  done

  # Switch back to management context
  run kubectl config use-context "${MGMT_CONTEXT}"
elif [ "${SKIP_ANRA}" = true ]; then
  log "Skipping ANRA (--skip-anra)"
else
  log "No --workload-context provided. Skipping ANRA installation."
  log "  To install ANRA later: helm install anra ${HELM_REPO}/anra -n ${ANRA_SYSTEM_NS} -f <values>"
fi

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
log ""
log "=== Bootstrap Complete ==="
log ""
log "Installed components:"
[ "${SKIP_ARGOCD}" = false ] && log "  ✅ ArgoCD          → ${ARGOCD_NAMESPACE} (management cluster)"
log "  ✅ anra-common     → ${ANRA_SYSTEM_NS} (shared CRDs)"
[ "${SKIP_ANPA}" = false ]   && log "  ✅ ANPA (Day 0)    → anpa-system (management cluster)"
[ "${SKIP_ANDA}" = false ]   && log "  ✅ ANDA (Day 1)    → anda-system (management cluster)"
if [ "${SKIP_ANRA}" = false ] && [ -n "${WORKLOAD_CONTEXTS}" ]; then
  IFS=',' read -ra CONTEXTS <<< "${WORKLOAD_CONTEXTS}"
  for CTX in "${CONTEXTS[@]}"; do
    log "  ✅ ANRA (Day 2)    → ${ANRA_SYSTEM_NS} ($(echo "${CTX}" | xargs))"
  done
fi
log ""
log "Lifecycle Management:"
log "  ANPA/ANDA: Upgrade via 'helm upgrade' with manual approval"
log "  ANRA:      Self-updates from ECR within maintenance windows"
log "  NFs:       Deployed by ANDA via ArgoCD (drain → sync → verify)"
