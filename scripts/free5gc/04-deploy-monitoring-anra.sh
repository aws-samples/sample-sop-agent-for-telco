#!/usr/bin/env bash
# Deploy Free5GC monitoring plus the ANDA/ANRA agents. ANPA is intentionally
# not installed: CloudFormation provisions the workshop infrastructure.
set -euo pipefail

BEDROCK_REGION="${BEDROCK_REGION:-us-west-2}"
FREE5GC_NAMESPACE="${FREE5GC_NAMESPACE:-free5gc}"
MONITORING_NAMESPACE="${MONITORING_NAMESPACE:-monitoring}"
ANRA_NAMESPACE="${ANRA_NAMESPACE:-anra-system}"
ANDA_NAMESPACE="${ANDA_NAMESPACE:-anda-system}"
KPS_RELEASE="${KPS_RELEASE:-kube-prometheus-stack}"
KPS_VERSION="${KPS_VERSION:-91.5.0}"
AGENT_IMAGE_REPOSITORY="${AGENT_IMAGE_REPOSITORY:-public.ecr.aws/t2j9i5y9/anra-workshop}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
MONITORING_DIR="${REPO_ROOT}/configs/free5gc-monitoring"
FREE5GC_CHART="${REPO_ROOT}/helm-charts/free5gc-bundle/free5gc-0.0.2.tgz"
ANRA_VALUES="${MONITORING_DIR}/anra-values.yaml"
CURRENT_CONTEXT="$(kubectl config current-context 2>/dev/null || true)"

if [ -z "${CURRENT_CONTEXT}" ]; then
  echo "ERROR: no current Kubernetes context is configured." >&2
  exit 1
fi

KUBE_CLUSTER_REFERENCE="$(kubectl config view --minify -o jsonpath='{.clusters[0].name}')"
if [ -z "${KUBE_CLUSTER_REFERENCE}" ]; then
  KUBE_CLUSTER_REFERENCE="${CURRENT_CONTEXT}"
fi
if [[ "${KUBE_CLUSTER_REFERENCE}" =~ ^arn:[^:]+:eks:([^:]+):[^:]+:cluster/(.+)$ ]]; then
  AWS_DEFAULT_REGION="${BASH_REMATCH[1]}"
  CLUSTER_NAME="${BASH_REMATCH[2]}"
else
  AWS_DEFAULT_REGION="${AWS_REGION:-${AWS_DEFAULT_REGION:-us-west-2}}"
  CLUSTER_NAME="${KUBE_CLUSTER_REFERENCE##*/}"
fi
export AWS_DEFAULT_REGION

AGENT_IMAGE_TAG="${AGENT_IMAGE_TAG:-$(git -C "${REPO_ROOT}" rev-parse --short=7 HEAD)}"
if [ -z "${AGENT_IMAGE_TAG}" ] || [ "${AGENT_IMAGE_TAG}" = "latest" ]; then
  echo "ERROR: AGENT_IMAGE_TAG must be an immutable image tag, not latest." >&2
  exit 1
fi

echo "==> Using Kubernetes context: ${CURRENT_CONTEXT}"
echo "==> Cluster metadata: name=${CLUSTER_NAME}, region=${AWS_DEFAULT_REGION}"
kubectl get --raw=/readyz >/dev/null

for required in \
  "${MONITORING_DIR}/kube-prometheus-stack-values.yaml" \
  "${MONITORING_DIR}/free5gc-alert-rules.yaml" \
  "${MONITORING_DIR}/dashboards/free5gc-core-overview.json" \
  "${ANRA_VALUES}" \
  "${REPO_ROOT}/alarm-references/free5gc.yaml" \
  "${FREE5GC_CHART}"; do
  test -f "${required}" || { echo "Missing required asset: ${required}" >&2; exit 1; }
done

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

# ANRA credentials must exist before the monitoring stack: Alertmanager mounts
# them to authenticate its webhook to ANRA (see kube-prometheus-stack-values).
#
# ANRA_AUTH_DISABLED=true turns ANRA's HTTP Basic auth off. Use it ONLY when an
# upstream gate authenticates every request before it reaches the pod (the
# Workshop Studio webui-auth stack: Cognito at the CloudFront edge). The secret
# then carries an empty password (works with images predating the explicit
# toggle) and the chart sets ANRA_AUTH_DISABLED on the pod.
# Auto-detect: when the Cognito/CloudFront "webui-auth" stack is present in this
# account (Workshop Studio deploys it right after the EKS stack), disable ANRA's
# own Basic auth and expose the UI on the NodePort that stack's ALB targets.
# Set ANRA_AUTH_DISABLED explicitly to override the detection either way.
ANRA_NODEPORT="${ANRA_NODEPORT:-30080}"
# The bastion role may describe a stack by name but is not granted
# cloudformation:ListStacks, which an unfiltered describe-stacks needs; query the
# conventional stack name first and only then fall back to the output scan.
WEBUI_AUTH_STACK_NAME="${WEBUI_AUTH_STACK_NAME:-webui-auth}"
if [ -z "${ANRA_AUTH_DISABLED:-}" ]; then
  WEBUI_AUTH_STACK="$(aws cloudformation describe-stacks --stack-name "${WEBUI_AUTH_STACK_NAME}" \
    --query "Stacks[?Outputs[?OutputKey=='HostedUiDomain']] | [0].StackName" --output text 2>/dev/null || true)"
  if [ -z "${WEBUI_AUTH_STACK}" ] || [ "${WEBUI_AUTH_STACK}" = None ]; then
    WEBUI_AUTH_STACK="$(aws cloudformation describe-stacks \
      --query "Stacks[?Outputs[?OutputKey=='HostedUiDomain']] | [0].StackName" --output text 2>/dev/null || true)"
  fi
  if [ -n "${WEBUI_AUTH_STACK}" ] && [ "${WEBUI_AUTH_STACK}" != None ]; then
    ANRA_AUTH_DISABLED=true
    ANRA_NODEPORT="$(aws cloudformation describe-stacks --stack-name "${WEBUI_AUTH_STACK}" \
      --query "Stacks[0].Outputs[?OutputKey=='NodePort'].OutputValue" --output text)"
    echo "Detected web UI auth stack ${WEBUI_AUTH_STACK}: ANRA auth delegated to the edge, NodePort ${ANRA_NODEPORT}."
  fi
fi
ANRA_AUTH_DISABLED="$(printf '%s' "${ANRA_AUTH_DISABLED:-false}" | tr '[:upper:]' '[:lower:]')"
case "${ANRA_AUTH_DISABLED}" in
  true|1|yes|on) ANRA_AUTH_DISABLED=true ;;
  *)             ANRA_AUTH_DISABLED=false ;;
esac
if [ "${ANRA_AUTH_DISABLED}" = true ]; then
  echo "WARNING: ANRA_AUTH_DISABLED=true - ANRA Basic auth is OFF; access must be gated upstream (Cognito/CloudFront)." >&2
fi
if ! kubectl get secret anra-workshop-credentials -n "${ANRA_NAMESPACE}" >/dev/null 2>&1; then
  if [ "${ANRA_AUTH_DISABLED}" = true ]; then
    ANRA_PASSWORD=""
  else
    ANRA_PASSWORD="${ANRA_PASSWORD:-$(openssl rand -hex 16)}"
  fi
  kubectl create secret generic anra-workshop-credentials -n "${ANRA_NAMESPACE}" \
    --from-literal=auth-username=admin \
    --from-literal=auth-password="${ANRA_PASSWORD}" \
    --from-literal=influxdb-token=''
  if [ -n "${ANRA_PASSWORD}" ]; then
    umask 077
    printf '%s\n' "${ANRA_PASSWORD}" > "${HOME}/anra-admin-password"
    echo "Generated ANRA password stored at ${HOME}/anra-admin-password"
  fi
elif [ "${ANRA_AUTH_DISABLED}" = true ]; then
  # Secret pre-exists (re-run): clear the password so the toggle is idempotent.
  kubectl patch secret anra-workshop-credentials -n "${ANRA_NAMESPACE}" \
    --type merge -p '{"data":{"auth-password":""}}'
  rm -f "${HOME}/anra-admin-password"
fi
# Mirror into the monitoring namespace (idempotent) for the Alertmanager mount.
kubectl get secret anra-workshop-credentials -n "${ANRA_NAMESPACE}" -o json | \
  jq --arg ns "${MONITORING_NAMESPACE}" \
    '{apiVersion, kind, type, data, metadata: {name: .metadata.name, namespace: $ns}}' | \
  kubectl apply -f -

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
  --set anra-common.enabled=false \
  --set-string image.repository="${AGENT_IMAGE_REPOSITORY}" \
  --set-string image.tag="${AGENT_IMAGE_TAG}" \
  --set-string aws.region="${AWS_DEFAULT_REGION}" \
  --set-string bedrock.region="${BEDROCK_REGION}" \
  --set-string config.cluster.name="${CLUSTER_NAME}" \
  --set-string config.cluster.region="${AWS_DEFAULT_REGION}" \
  --set-string deployment.helmRepo=file:///app/helm-charts/free5gc-bundle \
  --set infrastructureBootstrap.enabled=false \
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

helm upgrade --install anra "${REPO_ROOT}/helm-charts/anra" \
  -n "${ANRA_NAMESPACE}" \
  --values "${ANRA_VALUES}" \
  --set anra-common.enabled=false \
  --set-string image.repository="${AGENT_IMAGE_REPOSITORY}" \
  --set-string image.tag="${AGENT_IMAGE_TAG}" \
  --set-string bedrock.region="${BEDROCK_REGION}" \
  --set-string ssm.region="${AWS_DEFAULT_REGION}" \
  --set-string config.cluster.name="${CLUSTER_NAME}" \
  --set-string credentials.existingSecret=anra-workshop-credentials \
  --set auth.disabled="${ANRA_AUTH_DISABLED}" \
  --wait --timeout 5m

# Fail if ANPA was installed accidentally; this workshop uses CloudFormation.
if helm list --all-namespaces -q | grep -qx anpa; then
  echo 'ANPA release detected; workshop-v3 must use CloudFormation instead.' >&2
  exit 1
fi

# A moving tag (dev, or anything that is not a commit SHA) leaves the pod spec
# unchanged when the image behind it is overwritten, so Helm's --wait is a no-op.
# Force new pods so imagePullPolicy: Always actually re-resolves the tag.
if ! printf '%s' "${AGENT_IMAGE_TAG}" | grep -Eq '^[0-9a-f]{7,40}(@sha256:[0-9a-f]{64})?$'; then
  echo "Moving image tag '${AGENT_IMAGE_TAG}' (test loop): restarting agent pods to re-pull." >&2
  kubectl rollout restart deployment/anda -n "${ANDA_NAMESPACE}"
  kubectl rollout restart deployment/anra -n "${ANRA_NAMESPACE}"
fi
kubectl rollout status deployment/anda -n "${ANDA_NAMESPACE}" --timeout=300s
kubectl rollout status deployment/anra -n "${ANRA_NAMESPACE}" --timeout=300s

# Expose ANRA on the fixed NodePort the webui-auth ALB targets. Node security
# groups admit this port from the ALB only, so it is not reachable otherwise.
if [ "${ANRA_AUTH_DISABLED}" = true ]; then
  kubectl apply -n "${ANRA_NAMESPACE}" -f - <<EOF_SVC
apiVersion: v1
kind: Service
metadata:
  name: anra-nodeport
  labels:
    app.kubernetes.io/part-of: webui-auth
spec:
  type: NodePort
  externalTrafficPolicy: Cluster
  selector:
    app.kubernetes.io/name: anra
    app.kubernetes.io/instance: anra
  ports:
    - name: http
      port: 80
      targetPort: 8080
      nodePort: ${ANRA_NODEPORT}
      protocol: TCP
EOF_SVC
fi
kubectl get pods -n "${MONITORING_NAMESPACE}"
kubectl get pods -n "${ANRA_NAMESPACE}"
kubectl get pods -n "${ANDA_NAMESPACE}"

printf 'SOP 3 complete: monitoring=%s, ANRA=%s, ANDA=%s, ANPA=skipped\n' \
  "${MONITORING_NAMESPACE}" "${ANRA_NAMESPACE}" "${ANDA_NAMESPACE}"
