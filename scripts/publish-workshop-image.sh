#!/usr/bin/env bash
# Build and publish the workshop-v3 agent image to its authoritative Public ECR repository.
#
# Local use:
#   AWS_PROFILE=cse-dev-test scripts/publish-workshop-image.sh
#
# GitHub Actions runs the same implementation with OIDC credentials:
#   scripts/publish-workshop-image.sh --skip-validation --publish-dev
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PUBLIC_ECR_REPOSITORY="public.ecr.aws/t2j9i5y9/anra-workshop"
PUBLIC_ECR_REPOSITORY_NAME="anra-workshop"
PUBLIC_ECR_REGION="us-east-1"
EXPECTED_AWS_ACCOUNT_ID="833542146025"

DRY_RUN=false
SKIP_VALIDATION=false
PUBLISH_DEV=false
ALLOW_DIRTY=false

usage() {
  cat <<'EOF'
Usage: scripts/publish-workshop-image.sh [options]

Build and publish the current workshop-v3 commit to:
  public.ecr.aws/t2j9i5y9/anra-workshop

Options:
  --dry-run          Print the publish plan without calling AWS or Docker
  --skip-validation  Skip scripts/ci-local.sh (allowed only in CI or dry-run)
  --publish-dev      Also update the moving dev tag (test loop only)
  --allow-dirty      Permit a dirty tree in dry-run mode only
  -h, --help         Show this help

Local credentials:
  AWS_PROFILE=cse-dev-test scripts/publish-workshop-image.sh
EOF
}

while (($#)); do
  case "$1" in
    --dry-run) DRY_RUN=true ;;
    --skip-validation) SKIP_VALIDATION=true ;;
    --publish-dev) PUBLISH_DEV=true ;;
    --allow-dirty) ALLOW_DIRTY=true ;;
    -h | --help)
      usage
      exit 0
      ;;
    *)
      echo "ERROR: unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
  shift
done

cd "${REPO_ROOT}"

if ! command -v git >/dev/null 2>&1; then
  echo "ERROR: required command not found: git" >&2
  exit 1
fi

BRANCH="${GITHUB_REF_NAME:-$(git branch --show-current)}"
if [[ "${BRANCH}" != "workshop-v3" ]]; then
  echo "ERROR: image publishing is restricted to workshop-v3; current ref is '${BRANCH:-detached}'." >&2
  exit 1
fi

if [[ "${ALLOW_DIRTY}" == true && "${DRY_RUN}" != true ]]; then
  echo "ERROR: --allow-dirty is accepted only with --dry-run." >&2
  exit 1
fi

if [[ -n "$(git status --porcelain --untracked-files=normal)" && "${ALLOW_DIRTY}" != true ]]; then
  echo "ERROR: working tree is not clean; commit or stash changes before publishing." >&2
  exit 1
fi

if [[ "${SKIP_VALIDATION}" == true && "${CI:-false}" != true && "${DRY_RUN}" != true ]]; then
  echo "ERROR: --skip-validation is accepted only in CI or dry-run mode." >&2
  exit 1
fi

SHORT_SHA="$(git rev-parse --short=7 HEAD)"
if [[ ! "${SHORT_SHA}" =~ ^[0-9a-f]{7}$ ]]; then
  echo "ERROR: could not derive a seven-character Git SHA tag." >&2
  exit 1
fi

IMAGE_TAGS=("${SHORT_SHA}" "workshop-v3-${SHORT_SHA}")
if [[ "${PUBLISH_DEV}" == true ]]; then
  IMAGE_TAGS+=("dev")
fi

if [[ "${SKIP_VALIDATION}" != true ]]; then
  echo "==> Running workshop-v3 validation gates"
  bash scripts/ci-local.sh
fi

printf 'Workshop-v3 image publish plan:\n'
printf '  source:     %s@%s\n' "${BRANCH}" "${SHORT_SHA}"
printf '  account:    %s\n' "${EXPECTED_AWS_ACCOUNT_ID}"
printf '  repository: %s\n' "${PUBLIC_ECR_REPOSITORY}"
printf '  tags:'
printf ' %s' "${IMAGE_TAGS[@]}"
printf '\n'

if [[ "${DRY_RUN}" == true ]]; then
  echo "DRY RUN: AWS authentication, Docker build, and image pushes were not performed."
  exit 0
fi

for command in aws docker; do
  if ! command -v "${command}" >/dev/null 2>&1; then
    echo "ERROR: required command not found: ${command}" >&2
    exit 1
  fi
done

ACTUAL_AWS_ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text)"
if [[ "${ACTUAL_AWS_ACCOUNT_ID}" != "${EXPECTED_AWS_ACCOUNT_ID}" ]]; then
  echo "ERROR: refusing to publish from AWS account ${ACTUAL_AWS_ACCOUNT_ID}; expected ${EXPECTED_AWS_ACCOUNT_ID}." >&2
  exit 1
fi

ACTUAL_REPOSITORY_URI="$(aws ecr-public describe-repositories \
  --region "${PUBLIC_ECR_REGION}" \
  --repository-names "${PUBLIC_ECR_REPOSITORY_NAME}" \
  --query 'repositories[0].repositoryUri' \
  --output text)"
if [[ "${ACTUAL_REPOSITORY_URI}" != "${PUBLIC_ECR_REPOSITORY}" ]]; then
  echo "ERROR: repository identity mismatch: got '${ACTUAL_REPOSITORY_URI}', expected '${PUBLIC_ECR_REPOSITORY}'." >&2
  exit 1
fi

EXISTING_DIGEST="$(aws ecr-public describe-images \
  --region "${PUBLIC_ECR_REGION}" \
  --repository-name "${PUBLIC_ECR_REPOSITORY_NAME}" \
  --image-ids imageTag="${SHORT_SHA}" \
  --query 'imageDetails[0].imageDigest' \
  --output text 2>/dev/null || true)"
if [[ -n "${EXISTING_DIGEST}" && "${EXISTING_DIGEST}" != "None" ]]; then
  echo "Image already published: ${PUBLIC_ECR_REPOSITORY}:${SHORT_SHA}@${EXISTING_DIGEST}"
  echo "No tags were changed."
  exit 0
fi

echo "==> Logging in to Public ECR"
aws ecr-public get-login-password --region "${PUBLIC_ECR_REGION}" |
  docker login --username AWS --password-stdin public.ecr.aws

BUILD_ARGS=()
for tag in "${IMAGE_TAGS[@]}"; do
  BUILD_ARGS+=(--tag "${PUBLIC_ECR_REPOSITORY}:${tag}")
done

echo "==> Building ${PUBLIC_ECR_REPOSITORY}:${SHORT_SHA}"
docker build "${BUILD_ARGS[@]}" --file Dockerfile .

for tag in "${IMAGE_TAGS[@]}"; do
  echo "==> Pushing ${PUBLIC_ECR_REPOSITORY}:${tag}"
  docker push "${PUBLIC_ECR_REPOSITORY}:${tag}"
done

DIGEST="$(aws ecr-public describe-images \
  --region "${PUBLIC_ECR_REGION}" \
  --repository-name "${PUBLIC_ECR_REPOSITORY_NAME}" \
  --image-ids imageTag="${SHORT_SHA}" \
  --query 'imageDetails[0].imageDigest' \
  --output text)"
if [[ -z "${DIGEST}" || "${DIGEST}" == "None" ]]; then
  echo "ERROR: image push completed but Public ECR returned no digest." >&2
  exit 1
fi

printf '\nPublished workshop-v3 image:\n'
printf '  %s:%s@%s\n' "${PUBLIC_ECR_REPOSITORY}" "${SHORT_SHA}" "${DIGEST}"
printf '\nDeploy with:\n'
printf '  export AGENT_IMAGE_REPOSITORY=%s\n' "${PUBLIC_ECR_REPOSITORY}"
printf '  export AGENT_IMAGE_TAG=%s\n' "${SHORT_SHA}"

if [[ -n "${GITHUB_STEP_SUMMARY:-}" ]]; then
  {
    echo "### Workshop-v3 image published"
    echo "- \`${PUBLIC_ECR_REPOSITORY}:${SHORT_SHA}\` (deployment tag)"
    echo "- \`${PUBLIC_ECR_REPOSITORY}:workshop-v3-${SHORT_SHA}\`"
    if [[ "${PUBLISH_DEV}" == true ]]; then
      echo "- \`${PUBLIC_ECR_REPOSITORY}:dev\` (moving test-loop tag)"
    fi
    echo "- digest: \`${DIGEST}\`"
  } >>"${GITHUB_STEP_SUMMARY}"
fi
