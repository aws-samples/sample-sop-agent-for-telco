#!/bin/bash
# =============================================================================
# IND321 - Configure the cluster: kubeconfig, Multus + metrics-server, and the
# gtp5g kernel module on every worker node.
#
# Encodes lessons learned:
#   - The bastion reaches the EKS API over a PRIVATE endpoint IP; the CFN template
#     opens tcp/443 from the VPC CIDR to the cluster SG (EksApiFromVpcIngress).
#     If you deployed an older template, add that rule or this script will hang
#     on the first kubectl call.
#   - gtp5g is NOT installed by default and the AL2023 6.12 node needs the
#     kernel6.12-devel headers + gtp5g pinned to v0.9.15 (see install-gtp5g.sh).
#     We push install-gtp5g.sh to each worker via SSM so the UPF can start.
#
# Run on the bastion after the CloudFormation stack is complete.
# =============================================================================
set -euo pipefail

export STACK_NAME="${STACK_NAME:-telco-workshop-v3}"
export AWS_DEFAULT_REGION="${AWS_DEFAULT_REGION:-us-west-2}"
export CLUSTER_NAME="${CLUSTER_NAME:-eks-${STACK_NAME}}"
MULTUS_VERSION="${MULTUS_VERSION:-v4.0.2-eksbuild.1}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "==> Updating kubeconfig for ${CLUSTER_NAME}"
aws eks update-kubeconfig --region "${AWS_DEFAULT_REGION}" --name "${CLUSTER_NAME}"

echo "==> Waiting for nodes to be Ready"
kubectl wait --for=condition=Ready nodes --all --timeout=600s

echo "==> Installing Multus CNI (${MULTUS_VERSION}) and metrics-server"
kubectl apply -f "https://raw.githubusercontent.com/aws/amazon-vpc-cni-k8s/master/config/multus/${MULTUS_VERSION}/multus-daemonset-thick.yml"
kubectl apply -f https://github.com/kubernetes-sigs/metrics-server/releases/download/v0.7.2/components.yaml
kubectl -n kube-system rollout status daemonset/kube-multus-ds --timeout=300s || true

echo "==> Building/loading gtp5g on every worker node (required by the free5gc UPF)"
INSTIDS=$(aws ec2 describe-instances --region "${AWS_DEFAULT_REGION}" \
  --filters "Name=tag:eks:cluster-name,Values=${CLUSTER_NAME}" "Name=instance-state-name,Values=running" \
  --query "Reservations[].Instances[].InstanceId" --output text)
echo "   worker instances: ${INSTIDS}"

# Ship install-gtp5g.sh line-by-line as an SSM command document.
if [ -f "${SCRIPT_DIR}/install-gtp5g.sh" ]; then
  mapfile -t GTP_LINES < "${SCRIPT_DIR}/install-gtp5g.sh"
  PARAMS_JSON=$(printf '%s\n' "${GTP_LINES[@]}" | jq -R . | jq -s '{commands: .}')
  for i in ${INSTIDS}; do
    echo "   -> ${i}"
    CID=$(aws ssm send-command --instance-ids "$i" --region "${AWS_DEFAULT_REGION}" \
          --document-name "AWS-RunShellScript" --comment "install gtp5g" \
          --timeout-seconds 400 --parameters "$(echo "$PARAMS_JSON" | jq -c '{commands: .commands}')" \
          --query "Command.CommandId" --output text 2>/dev/null)
    # Wait for completion
    for _ in $(seq 1 60); do
      sleep 6
      ST=$(aws ssm get-command-invocation --command-id "$CID" --instance-id "$i" --region "${AWS_DEFAULT_REGION}" --query "Status" --output text 2>/dev/null)
      [ "$ST" = "Success" ] || [ "$ST" = "Failed" ] && break
    done
    RES=$(aws ssm get-command-invocation --command-id "$CID" --instance-id "$i" --region "${AWS_DEFAULT_REGION}" --query "StandardOutputContent" --output text 2>/dev/null | grep -E "GTP5G_LOADED_OK|GTP5G_LOAD_FAILED|version:" || true)
    echo "      ${RES:-(no marker; check SSM output for $CID)}"
  done
else
  echo "   WARNING: install-gtp5g.sh not found next to this script; load gtp5g manually."
fi

echo "==> Current cluster state"
kubectl get nodes -o wide
kubectl get daemonset -n kube-system | grep -i multus || true
kubectl get deployment metrics-server -n kube-system || true
echo "Done. Next: scripts/03-deploy-workloads.sh"
