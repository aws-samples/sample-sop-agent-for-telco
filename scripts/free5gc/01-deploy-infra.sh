#!/usr/bin/env bash
# Deploy the workshop-v3 VPC, EKS, Multus, gtp5g, and bastion substrate.
set -euo pipefail

export STACK_NAME="${STACK_NAME:-telco-workshop-v3}"
export AWS_DEFAULT_REGION="${AWS_DEFAULT_REGION:-us-west-2}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
TEMPLATE="${TEMPLATE:-${REPO_ROOT}/infra/cloudformation/vpc-eks-multus.yaml}"
AZ1="${AZ1:-${AWS_DEFAULT_REGION}a}"
AZ2="${AZ2:-${AWS_DEFAULT_REGION}b}"
ALLOWED_EXTERNAL_CIDR="${ALLOWED_EXTERNAL_CIDR:-127.0.0.1/32}"
BASTION_KEY="${BASTION_KEY:?Set BASTION_KEY to an existing EC2 key pair name}"
WORKER_KEY="${WORKER_KEY:-${BASTION_KEY}}"

test -f "${TEMPLATE}"
aws cloudformation validate-template \
  --template-body "file://${TEMPLATE}" --region "${AWS_DEFAULT_REGION}" >/dev/null

printf 'Deploying %s in %s; external ingress=%s\n' \
  "${STACK_NAME}" "${AWS_DEFAULT_REGION}" "${ALLOWED_EXTERNAL_CIDR}"
aws cloudformation deploy \
  --stack-name "${STACK_NAME}" \
  --template-file "${TEMPLATE}" \
  --region "${AWS_DEFAULT_REGION}" \
  --capabilities CAPABILITY_NAMED_IAM \
  --parameter-overrides \
    "AvailabilityZones=${AZ1},${AZ2}" \
    "BastionKeyPairName=${BASTION_KEY}" \
    "EksWorkerKeyName=${WORKER_KEY}" \
    "AllowedExternalAccessCidr=${ALLOWED_EXTERNAL_CIDR}"

aws cloudformation describe-stacks \
  --stack-name "${STACK_NAME}" --region "${AWS_DEFAULT_REGION}" \
  --query 'Stacks[0].Outputs' --output table
