#!/bin/bash
# CI Step: E2E tests against real Dell iDRAC BMCs
# Assumes cross-account role into CSE Dev (833542146025) for EKS access.
# Required env vars: BMC_IPS, BMC_USER, BMC_PASS (from Secrets Manager)
set -euo pipefail

EKS_CLUSTER="site-002-workload"
DEPLOY_REGION="us-west-1"
CROSS_ACCOUNT_ROLE="arn:aws:iam::833542146025:role/TelcoAna-AssumeRole-187692046528-beta-us-west-1"

if [ -z "${BMC_IPS:-}" ] || [ -z "${BMC_PASS:-}" ]; then
  echo "ERROR: BMC_IPS and BMC_PASS must be set (from Secrets Manager)"
  exit 2
fi

echo "▶ Configuring kubectl (cross-account)..."
aws eks update-kubeconfig --name "$EKS_CLUSTER" --region "$DEPLOY_REGION" --role-arn "$CROSS_ACCOUNT_ROLE"

# Find ANPA pod
ANPA_POD=$(kubectl get pod -n anpa-system -l app.kubernetes.io/name=anpa \
  --field-selector=status.phase=Running \
  -o jsonpath='{.items[0].metadata.name}')
[ -n "$ANPA_POD" ] || { echo "✗ no Running ANPA pod found"; exit 1; }
echo "▶ Running Day 0 test inside $ANPA_POD"

# E2E Day-0 test (runs inside ANPA pod)
cat platform/tests/day0-bmc-discovery-test.sh | kubectl exec -i -n anpa-system "$ANPA_POD" \
  -- env BMC_IPS="$BMC_IPS" BMC_USER="${BMC_USER:-root}" BMC_PASS="$BMC_PASS" \
  REQUIRE_HANDOFF=1 bash -s

# E2E Integration test (runs from this host, kubectl exec into pod for Redfish)
echo "▶ Running integration test..."
KUBE_CTX=$(kubectl config current-context)
python3 platform/tests/live-integration-test.py \
  --kubectl-context "$KUBE_CTX" \
  --bmc-ips "$BMC_IPS" \
  --bmc-user "${BMC_USER:-root}" \
  --bmc-pass "$BMC_PASS"

echo "✅ All E2E tests passed"
