#!/usr/bin/env bash
# Deploy Free5GC monitoring plus the ANDA/ANRA agents. ANPA is intentionally
# not installed: CloudFormation provisions the workshop infrastructure.
set -euo pipefail

STACK_NAME="${STACK_NAME:-telco-workshop-v3}"
CLUSTER_NAME="${CLUSTER_NAME:-eks-${STACK_NAME}}"
AWS_DEFAULT_REGION="${AWS_DEFAULT_REGION:-us-west-2}"
FREE5GC_NAMESPACE="${FREE5GC_NAMESPACE:-free5gc}"
MONITORING_NAMESPACE="${MONITORING_NAMESPACE:-monitoring}"
ANRA_NAMESPACE="${ANRA_NAMESPACE:-anra-system}"
ANDA_NAMESPACE="${ANDA_NAMESPACE:-anda-system}"
KPS_RELEASE="${KPS_RELEASE:-kube-prometheus-stack}"
KPS_VERSION="${KPS_VERSION:-91.5.0}"
AGENT_IMAGE_REPOSITORY="${AGENT_IMAGE_REPOSITORY:-public.ecr.aws/t2j9i5y9/anra-workshop}"
AGENT_IMAGE_TAG="${AGENT_IMAGE_TAG:?Set AGENT_IMAGE_TAG to an immutable workshop-v3 image tag}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
MONITORING_DIR="${REPO_ROOT}/configs/free5gc-monitoring"
FREE5GC_CHART="${REPO_ROOT}/helm-charts/free5gc-bundle/free5gc-0.0.2.tgz"
ANRA_VALUES="${MONITORING_DIR}/anra-values.yaml"

for required in \
  "${MONITORING_DIR}/kube-prometheus-stack-values.yaml" \
  "${MONITORING_DIR}/free5gc-alert-rules.yaml" \
  "${MONITORING_DIR}/dashboards/free5gc-core-overview.json" \
  "${ANRA_VALUES}" \
  "${REPO_ROOT}/alarm-references/free5gc.yaml" \
  "${FREE5GC_CHART}"; do
  test -f "${required}" || { echo "Missing required asset: ${required}" >&2; exit 1; }
done

aws eks update-kubeconfig --region "${AWS_DEFAULT_REGION}" --name "${CLUSTER_NAME}"
kubectl create namespace "${MONITORING_NAMESPACE}" --dry-run=client -o yaml | kubectl apply -f -
kubectl create namespace "${ANRA_NAMESPACE}" --dry-run=client -o yaml | kubectl apply -f -
kubectl create namespace "${ANDA_NAMESPACE}" --dry-run=client -o yaml | kubectl apply -f -

if ! kubectl get secret free5gc-grafana-admin -n "${MONITORING_NAMESPACE}" >/dev/null 2>&1; then
  GRAFANA_PASSWORD="${GRAFANA_PASSWORD:-$(openssl rand -hex 16)}"
  kubectl create secret generic free5gc-grafana-admin -n "${MONITORING_NAMESPACE}" \
    --from-literal=admin-user=admin \
    --from-literal=admin-password="${GRAFANA_PASSWORD}"
  umask 077
  printf '%s\n' "${GRAFANA_PASSWORD}" > "${HOME}/grafana-admin-password"
  echo "Generated Grafana password stored at ${HOME}/grafana-admin-password"
fi

helm repo add prometheus-community https://prometheus-community.github.io/helm-charts >/dev/null 2>&1 || true
helm repo update prometheus-community >/dev/null
helm upgrade --install "${KPS_RELEASE}" prometheus-community/kube-prometheus-stack \
  --version "${KPS_VERSION}" --namespace "${MONITORING_NAMESPACE}" \
  --values "${MONITORING_DIR}/kube-prometheus-stack-values.yaml" \
  --wait --timeout 10m

kubectl apply -n "${MONITORING_NAMESPACE}" \
  -f "${MONITORING_DIR}/free5gc-alert-rules.yaml"
kubectl create configmap free5gc-core-overview-dashboard \
  -n "${MONITORING_NAMESPACE}" \
  --from-file=free5gc-core-overview.json="${MONITORING_DIR}/dashboards/free5gc-core-overview.json" \
  --dry-run=client -o yaml | \
  kubectl label --local -f - grafana_dashboard=1 -o yaml | kubectl apply -f -

# If Free5GC was installed before the Prometheus Operator CRDs existed, enable
# its PodMonitor now without changing the validated chart values.
if helm status free5gc -n "${FREE5GC_NAMESPACE}" >/dev/null 2>&1; then
  helm upgrade free5gc "${FREE5GC_CHART}" -n "${FREE5GC_NAMESPACE}" \
    --reuse-values --set metrics.enable=true --set metrics.podMonitor.enable=true
fi

# Install only the shared CRDs, ANDA, and ANRA. ANPA is deliberately omitted.
helm dependency build "${REPO_ROOT}/helm-charts/anda" >/dev/null
helm dependency build "${REPO_ROOT}/helm-charts/anra" >/dev/null
helm upgrade --install anra-common "${REPO_ROOT}/helm-charts/anra-common" \
  -n "${ANRA_NAMESPACE}" --wait --timeout 3m
helm upgrade --install anda "${REPO_ROOT}/helm-charts/anda" \
  -n "${ANDA_NAMESPACE}" \
  --set-string image.repository="${AGENT_IMAGE_REPOSITORY}" \
  --set-string image.tag="${AGENT_IMAGE_TAG}" \
  --set-string aws.region="${AWS_DEFAULT_REGION}" \
  --set-string bedrock.region="${AWS_DEFAULT_REGION}" \
  --set argocd.enabled=false \
  --set nfCatalog.srsran.enabled=false \
  --set nfCatalog.open5gs.enabled=false \
  --set nfCatalog.upf.enabled=false \
  --set nfCatalog.monitoring.enabled=false \
  --set nfCatalog.free5gc.enabled=true \
  --set-string nfCatalog.free5gc.chart=/app/helm-charts/free5gc-bundle/free5gc-0.0.2.tgz \
  --set-string nfCatalog.free5gc.version=0.0.2 \
  --set-string nfCatalog.free5gc.namespace="${FREE5GC_NAMESPACE}" \
  --wait --timeout 5m

if ! kubectl get secret anra-workshop-credentials -n "${ANRA_NAMESPACE}" >/dev/null 2>&1; then
  ANRA_PASSWORD="${ANRA_PASSWORD:-$(openssl rand -hex 16)}"
  kubectl create secret generic anra-workshop-credentials -n "${ANRA_NAMESPACE}" \
    --from-literal=auth-username=admin \
    --from-literal=auth-password="${ANRA_PASSWORD}" \
    --from-literal=influxdb-token=''
  umask 077
  printf '%s\n' "${ANRA_PASSWORD}" > "${HOME}/anra-admin-password"
  echo "Generated ANRA password stored at ${HOME}/anra-admin-password"
fi

helm upgrade --install anra "${REPO_ROOT}/helm-charts/anra" \
  -n "${ANRA_NAMESPACE}" \
  --values "${ANRA_VALUES}" \
  --set-string image.repository="${AGENT_IMAGE_REPOSITORY}" \
  --set-string image.tag="${AGENT_IMAGE_TAG}" \
  --set-string bedrock.region="${AWS_DEFAULT_REGION}" \
  --set-string ssm.region="${AWS_DEFAULT_REGION}" \
  --set-string config.cluster.name="${CLUSTER_NAME}" \
  --set-string credentials.existingSecret=anra-workshop-credentials \
  --wait --timeout 5m

# Fail if ANPA was installed accidentally; this workshop uses CloudFormation.
if helm list --all-namespaces -q | grep -qx anpa; then
  echo 'ANPA release detected; workshop-v3 must use CloudFormation instead.' >&2
  exit 1
fi

kubectl rollout status deployment/anda -n "${ANDA_NAMESPACE}" --timeout=300s
kubectl rollout status deployment/anra -n "${ANRA_NAMESPACE}" --timeout=300s
kubectl get pods -n "${MONITORING_NAMESPACE}"
kubectl get pods -n "${ANRA_NAMESPACE}"
kubectl get pods -n "${ANDA_NAMESPACE}"

printf 'SOP 3 complete: monitoring=%s, ANRA=%s, ANDA=%s, ANPA=skipped\n' \
  "${MONITORING_NAMESPACE}" "${ANRA_NAMESPACE}" "${ANDA_NAMESPACE}"
