#!/usr/bin/env bash
# Bring up the workshop-v3 Free5GC environment from a local AWS CLI session.
# CloudFormation creates the VPC/EKS/Multus substrate. Kubernetes resources are
# installed on the bastion through SSM in the same order used by IND321.
set -euo pipefail

export STACK_NAME="${STACK_NAME:-telco-workshop-v3}"
export AWS_DEFAULT_REGION="${AWS_DEFAULT_REGION:-us-west-2}"
export CLUSTER_NAME="${CLUSTER_NAME:-eks-${STACK_NAME}}"
AGENT_IMAGE_REPOSITORY="${AGENT_IMAGE_REPOSITORY:-public.ecr.aws/t2j9i5y9/anra-workshop}"
AGENT_IMAGE_TAG="${AGENT_IMAGE_TAG:?Set AGENT_IMAGE_TAG to an immutable workshop-v3 image tag}"
ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text)"
REGION_KEY="${AWS_DEFAULT_REGION//-/}"
S3_BUCKET="${S3_BUCKET:-${STACK_NAME}-${ACCOUNT_ID}-${REGION_KEY}}"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

printf 'Workshop-v3 bring-up: stack=%s cluster=%s region=%s\n' \
  "${STACK_NAME}" "${CLUSTER_NAME}" "${AWS_DEFAULT_REGION}"

bash "${REPO_ROOT}/scripts/free5gc/01-deploy-infra.sh"

BASTION_ID="$(aws cloudformation describe-stacks \
  --stack-name "${STACK_NAME}" --region "${AWS_DEFAULT_REGION}" \
  --query "Stacks[0].Outputs[?OutputKey=='BastionInstanceId'].OutputValue" \
  --output text)"
test -n "${BASTION_ID}"

aws s3 mb "s3://${S3_BUCKET}" --region "${AWS_DEFAULT_REGION}" 2>/dev/null || true
aws s3 sync "${REPO_ROOT}" "s3://${S3_BUCKET}/repo/" \
  --exclude '.git/*' --exclude 'build/*' --exclude '**/__pycache__/*' \
  --exclude '.pytest_cache/*' --exclude '.ruff_cache/*' \
  --exclude 'configs/influxdb/*' --exclude 'configs/telegraf/*' --no-progress \
  --region "${AWS_DEFAULT_REGION}"

run_on_bastion() {
  local label="$1"
  local command="$2"
  local parameters command_id status
  printf '==> [bastion] %s\n' "${label}"
  parameters="$(jq -nc --arg command "${command}" '{commands:[$command]}')"
  command_id="$(aws ssm send-command \
    --instance-ids "${BASTION_ID}" --region "${AWS_DEFAULT_REGION}" \
    --document-name AWS-RunShellScript --comment "${label}" \
    --timeout-seconds 1800 --parameters "${parameters}" \
    --query 'Command.CommandId' --output text)"
  while true; do
    sleep 8
    status="$(aws ssm get-command-invocation \
      --command-id "${command_id}" --instance-id "${BASTION_ID}" \
      --region "${AWS_DEFAULT_REGION}" --query Status --output text 2>/dev/null || true)"
    case "${status}" in
      Success|Failed|TimedOut|Cancelled) break ;;
    esac
  done
  aws ssm get-command-invocation --command-id "${command_id}" \
    --instance-id "${BASTION_ID}" --region "${AWS_DEFAULT_REGION}" \
    --query StandardOutputContent --output text || true
  if [[ "${status}" != Success ]]; then
    aws ssm get-command-invocation --command-id "${command_id}" \
      --instance-id "${BASTION_ID}" --region "${AWS_DEFAULT_REGION}" \
      --query StandardErrorContent --output text || true
    printf 'Remote step failed: %s (%s)\n' "${label}" "${status}" >&2
    return 1
  fi
}

REMOTE_ROOT=/root/workshop-v3
COMMON_ENV="export HOME=/root STACK_NAME=${STACK_NAME} CLUSTER_NAME=${CLUSTER_NAME} AWS_DEFAULT_REGION=${AWS_DEFAULT_REGION}"
run_on_bastion 'stage workshop-v3 source' \
  "mkdir -p ${REMOTE_ROOT}; aws s3 sync s3://${S3_BUCKET}/repo/ ${REMOTE_ROOT}/ --no-progress; chmod +x ${REMOTE_ROOT}/scripts/free5gc/*.sh ${REMOTE_ROOT}/tests/free5gc/*.sh"
run_on_bastion 'configure Multus and gtp5g' \
  "${COMMON_ENV}; cd ${REMOTE_ROOT}; bash scripts/free5gc/02-configure-cluster.sh"
run_on_bastion 'deploy Free5GC and PacketRusher' \
  "${COMMON_ENV}; cd ${REMOTE_ROOT}; bash scripts/free5gc/03-deploy-workloads.sh"
run_on_bastion 'validate the Free5GC data path' \
  "${COMMON_ENV}; cd ${REMOTE_ROOT}; bash tests/free5gc/run-tests.sh"
run_on_bastion 'deploy monitoring, ANDA, and ANRA (ANPA skipped)' \
  "${COMMON_ENV}; export AGENT_IMAGE_REPOSITORY=${AGENT_IMAGE_REPOSITORY} AGENT_IMAGE_TAG=${AGENT_IMAGE_TAG}; cd ${REMOTE_ROOT}; bash scripts/free5gc/04-deploy-monitoring-anra.sh"

printf 'Workshop-v3 bring-up complete. Bastion instance: %s\n' "${BASTION_ID}"
