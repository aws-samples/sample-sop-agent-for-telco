#!/usr/bin/env bash
# Remove workshop-v3 Kubernetes releases, then delete the CloudFormation stack.
# This is destructive and must be run only for the disposable workshop stack.
set -euo pipefail

STACK_NAME="${STACK_NAME:-telco-workshop-v3}"
AWS_DEFAULT_REGION="${AWS_DEFAULT_REGION:-us-west-2}"
FREE5GC_NAMESPACE="${FREE5GC_NAMESPACE:-free5gc}"
MONITORING_NAMESPACE="${MONITORING_NAMESPACE:-monitoring}"
ANRA_NAMESPACE="${ANRA_NAMESPACE:-anra-system}"
ANDA_NAMESPACE="${ANDA_NAMESPACE:-anda-system}"

helm uninstall anra -n "${ANRA_NAMESPACE}" 2>/dev/null || true
helm uninstall anda -n "${ANDA_NAMESPACE}" 2>/dev/null || true
helm uninstall anra-common -n "${ANRA_NAMESPACE}" 2>/dev/null || true
helm uninstall kube-prometheus-stack -n "${MONITORING_NAMESPACE}" 2>/dev/null || true
helm uninstall packetrusher -n "${FREE5GC_NAMESPACE}" 2>/dev/null || true
helm uninstall free5gc -n "${FREE5GC_NAMESPACE}" 2>/dev/null || true
kubectl delete namespace "${ANRA_NAMESPACE}" "${ANDA_NAMESPACE}" \
  "${MONITORING_NAMESPACE}" "${FREE5GC_NAMESPACE}" --ignore-not-found

aws cloudformation delete-stack --stack-name "${STACK_NAME}" --region "${AWS_DEFAULT_REGION}"
aws cloudformation wait stack-delete-complete --stack-name "${STACK_NAME}" --region "${AWS_DEFAULT_REGION}"
echo "Deleted workshop-v3 stack ${STACK_NAME}."
