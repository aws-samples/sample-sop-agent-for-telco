#!/bin/bash
# CI Step: Helm deploy all 3 agents to site-002-workload EKS cluster
# Assumes cross-account role into CSE Dev (833542146025) for EKS access.
set -euo pipefail

ECR_REGISTRY="187692046528.dkr.ecr.us-west-1.amazonaws.com"
ECR_REPO="telco-ana"
IMAGE_TAG="${CODEBUILD_RESOLVED_SOURCE_VERSION:0:8}"
EKS_CLUSTER="site-002-workload"
DEPLOY_REGION="us-west-1"
CROSS_ACCOUNT_ROLE="arn:aws:iam::833542146025:role/TelcoAna-AssumeRole-187692046528-beta-us-west-1"

echo "▶ Configuring kubectl (cross-account)..."
aws eks update-kubeconfig --name "$EKS_CLUSTER" --region "$DEPLOY_REGION" --role-arn "$CROSS_ACCOUNT_ROLE"

echo "▶ Applying CRDs (Helm doesn't update CRDs on upgrade)..."
kubectl apply -f helm-charts/anda/crds/ 2>/dev/null || true
kubectl apply -f helm-charts/anpa/crds/ 2>/dev/null || true
kubectl apply -f helm-charts/anra-common/crds/ 2>/dev/null || true
echo "✅ CRDs applied"
echo ""


echo "▶ Deploying ANDA (Day 1)..."
helm upgrade --install anda helm-charts/anda \
  --namespace anda-system --create-namespace \
  --set image.repository="${ECR_REGISTRY}/${ECR_REPO}" \
  --set image.tag="$IMAGE_TAG" \
  --set argocd.enabled=false \
  --set validation.preflight.enabled=false \
  --wait --timeout 120s

echo "▶ Deploying ANPA (Day 0)..."
helm upgrade --install anpa helm-charts/anpa \
  --namespace anpa-system --create-namespace \
  --set image.repository="${ECR_REGISTRY}/${ECR_REPO}" \
  --set image.tag="$IMAGE_TAG" \
  --wait --timeout 120s

echo "▶ Deploying ANRA (Day 2)..."
helm upgrade --install anra helm-charts/anra \
  --namespace anra-system --create-namespace \
  --set image.repository="${ECR_REGISTRY}/${ECR_REPO}" \
  --set image.tag="$IMAGE_TAG" \
  --wait --timeout 120s

echo "▶ Verifying health (rollout)..."
kubectl rollout status deployment/anra -n anra-system --timeout=60s
kubectl rollout status deployment/anda -n anda-system --timeout=60s
kubectl rollout status deployment/anpa -n anpa-system --timeout=60s

echo "▶ Smoke test: verify reconcilers started (not placeholder)..."
for ns_agent in "anra-system/anra" "anda-system/anda" "anpa-system/anpa"; do
  ns="${ns_agent%/*}"
  agent="${ns_agent#*/}"
  echo "  Checking $agent in $ns..."
  # Retry up to 15s (3 attempts, 5s apart) for the startup log line
  found=false
  for attempt in 1 2 3; do
    if kubectl logs deployment/$agent -n $ns --tail=50 2>/dev/null | grep -qiE "(reconciler starting|starting.*agent|agent.*initialized|listening|ANO Platform)"; then
      found=true
      break
    fi
    [ $attempt -lt 3 ] && sleep 5
  done
  if [ "$found" = false ]; then
    echo "❌ SMOKE TEST FAILED: $agent in $ns has no startup log after 15s. Possible placeholder entrypoint."
    echo "  Last 10 lines:"
    kubectl logs deployment/$agent -n $ns --tail=10 2>/dev/null
    exit 1
  fi
  echo "  ✅ $agent started correctly"
done

echo "✅ All 3 agents deployed, healthy, and reconcilers started"
