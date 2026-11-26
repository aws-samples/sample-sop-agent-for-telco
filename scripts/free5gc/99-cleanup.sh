#!/usr/bin/env bash
# Remove the workshop releases, namespaces and DeploymentPlans from the EKS
# cluster. The cluster, nodes and CloudFormation stacks are left in place.
#
# Pass --delete-stack to also delete the CloudFormation stack named by
# STACK_NAME. That is destructive: only use it for your own disposable stack.
# On the workshop bastion STACK_NAME is the event's workshop-infra stack.
set -euo pipefail

DELETE_STACK=0
for arg in "$@"; do
  case "$arg" in
    --delete-stack) DELETE_STACK=1 ;;
    -h | --help) sed -n '2,8p' "$0"; exit 0 ;;
    *) echo "unknown argument: $arg (use --delete-stack or --help)" >&2; exit 2 ;;
  esac
done

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
# DeploymentPlans from earlier runs, wherever they are (the CRD stays).
if kubectl get crd deploymentplans.deployment.anda.aws.io >/dev/null 2>&1; then
  kubectl delete deploymentplans.deployment.anda.aws.io --all -A --ignore-not-found
fi
echo "Removed the workshop releases, namespaces and DeploymentPlans from the cluster."

if [ "${DELETE_STACK}" -ne 1 ]; then
  echo "CloudFormation stack ${STACK_NAME} was not touched (pass --delete-stack to delete it)."
  exit 0
fi

aws cloudformation delete-stack --stack-name "${STACK_NAME}" --region "${AWS_DEFAULT_REGION}"
aws cloudformation wait stack-delete-complete --stack-name "${STACK_NAME}" --region "${AWS_DEFAULT_REGION}"
echo "Deleted workshop-v3 stack ${STACK_NAME}."
