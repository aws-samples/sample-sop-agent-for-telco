#!/bin/bash
# =============================================================================
# Configure the Kubernetes context prepared by Workshop Studio with the pinned
# Multus and metrics-server components required by the Free5GC workshop.
#
# CloudFormation owns the EKS cluster and worker-host prerequisites. This script
# deliberately does not call update-kubeconfig, EC2, or SSM: it operates only on
# the context selected before invocation and fails if that context is unusable.
# =============================================================================
set -euo pipefail

MULTUS_VERSION="${MULTUS_VERSION:-v4.0.2-eksbuild.1}"
CURRENT_CONTEXT="$(kubectl config current-context 2>/dev/null || true)"

if [ -z "${CURRENT_CONTEXT}" ]; then
  echo "ERROR: no current Kubernetes context is configured." >&2
  exit 1
fi

echo "==> Using Kubernetes context: ${CURRENT_CONTEXT}"
kubectl get --raw=/readyz >/dev/null

echo "==> Waiting for nodes to be Ready"
kubectl wait --for=condition=Ready nodes --all --timeout=600s

echo "==> Installing Multus CNI (${MULTUS_VERSION}) and metrics-server"
kubectl apply -f "https://raw.githubusercontent.com/aws/amazon-vpc-cni-k8s/master/config/multus/${MULTUS_VERSION}/multus-daemonset-thick.yml"
kubectl apply -f https://github.com/kubernetes-sigs/metrics-server/releases/download/v0.7.2/components.yaml
kubectl -n kube-system rollout status daemonset/kube-multus-ds --timeout=300s
kubectl -n kube-system rollout status deployment/metrics-server --timeout=300s

echo "==> Current cluster state"
kubectl get nodes -o wide
kubectl get daemonset kube-multus-ds -n kube-system
kubectl get deployment metrics-server -n kube-system
echo "Done. Next: scripts/free5gc/03-deploy-workloads.sh"
