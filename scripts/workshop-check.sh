#!/usr/bin/env bash
# workshop-check.sh - participant readiness check for the workshop bastion.
#
# Runs on the bastion as ec2-user and answers one question: is this environment
# ready for the labs? Every check prints a single [OK]/[WARN]/[FAIL] line, every
# failure carries a remediation hint, and the exit code is non-zero if anything
# failed. Read-only, idempotent, safe to rerun after a facilitator intervention.
#
#   bash scripts/workshop-check.sh             run every check
#   bash scripts/workshop-check.sh --verbose   also print raw command output
#   bash scripts/workshop-check.sh --skip-bedrock --skip-webui
#
# Rerun it any time, e.g. after reconnecting to a lost session: it also reports
# Helm releases stuck in a pending state, which block every later SOP.
#
# Full command output is always written to $LOG (default /tmp/workshop-check.log)
# and the summary to ~/.workshop-check so a facilitator can collect it.
#
# Required bastion role permissions (all present in BastionEC2Role):
#   cloudformation:DescribeStacks, eks:DescribeCluster, eks:ListNodegroups,
#   eks:DescribeNodegroup, bedrock:InvokeModel (via the project model resolver).
# EKS add-on health is read through kubectl because the role has no eks:DescribeAddon.
set -uo pipefail

EXPECTED_REGION="${EXPECTED_REGION:-us-west-2}"
WORKSHOP_DIR="${WORKSHOP_DIR:-$HOME/environment/workshop}"
STATUS_FILE="${STATUS_FILE:-$HOME/.workshop-status}"
RESULT_FILE="${RESULT_FILE:-$HOME/.workshop-check}"
LOG="${LOG:-/tmp/workshop-check.log}"
BEDROCK_TIMEOUT="${BEDROCK_TIMEOUT:-90}"

VERBOSE=false
SKIP_BEDROCK=false
SKIP_WEBUI=false
for arg in "$@"; do
  case "$arg" in
    --verbose | -v) VERBOSE=true ;;
    --skip-bedrock) SKIP_BEDROCK=true ;;
    --skip-webui) SKIP_WEBUI=true ;;
    -h | --help)
      sed -n '2,15p' "$0"
      exit 0
      ;;
    *)
      echo "unknown argument: $arg (use --verbose, --skip-bedrock, --skip-webui, --help)" >&2
      exit 2
      ;;
  esac
done

# Defaults match what the bastion bootstrap writes to ~/.bashrc; a non-login
# shell (e.g. `ssm-user` before `sudo su - ec2-user`) will not have them.
STACK_NAME="${STACK_NAME:-}"
CLUSTER_NAME="${CLUSTER_NAME:-${STACK_NAME:+eks-$STACK_NAME}}"
AWS_DEFAULT_REGION="${AWS_DEFAULT_REGION:-}"
export AWS_DEFAULT_REGION AWS_PAGER=""
export KUBECONFIG="${KUBECONFIG:-$HOME/.kube/config}"
export PYTHONPATH="${PYTHONPATH:-$WORKSHOP_DIR/src}"

# ----------------------------------------------------------------------------- output
if [ -t 1 ]; then
  C_OK=$'\033[32m' C_WARN=$'\033[33m' C_FAIL=$'\033[31m' C_DIM=$'\033[2m' C_OFF=$'\033[0m'
else
  C_OK='' C_WARN='' C_FAIL='' C_DIM='' C_OFF=''
fi

FAILS=0
WARNS=0
SUMMARY=()

: > "$LOG"
log() { printf '%s\n' "$*" >> "$LOG"; }

# run <cmd...>: run a command, append its output to the log, echo it to stdout
# for the caller to capture. Never aborts the script.
run() {
  local out rc
  log "\$ $*"
  out="$("$@" 2>&1)"
  rc=$?
  log "$out"
  log "(exit $rc)"
  $VERBOSE && printf '%s\n' "$out" | sed 's/^/        | /' >&2
  printf '%s' "$out"
  return $rc
}

# report <status> <label> <detail> [hint]
report() {
  local status=$1 label=$2 detail=$3 hint=${4:-} colour tag
  case "$status" in
    OK)   colour=$C_OK;   tag='[OK]  ' ;;
    WARN) colour=$C_WARN; tag='[WARN]'; WARNS=$((WARNS + 1)) ;;
    FAIL) colour=$C_FAIL; tag='[FAIL]'; FAILS=$((FAILS + 1)) ;;
    SKIP) colour=$C_DIM;  tag='[SKIP]' ;;
  esac
  printf '  %s%s%s %-30s %s\n' "$colour" "$tag" "$C_OFF" "$label" "$detail"
  [ -n "$hint" ] && printf '         %s-> %s%s\n' "$C_DIM" "$hint" "$C_OFF"
  SUMMARY+=("$tag $label: $detail")
  log "RESULT $tag $label: $detail${hint:+ -> $hint}"
}

FACILITATOR="Contact the facilitator. Full log: $LOG"

# ----------------------------------------------------------------------------- checks
check_user() {
  if [ "$(id -un)" = "ec2-user" ]; then
    report OK "Running as ec2-user" "$(id -un)@$(hostname -s)"
  else
    report WARN "Running as ec2-user" "you are $(id -un)" \
      "Run 'sudo su - ec2-user' first; the workshop tools and kubeconfig belong to ec2-user."
  fi
}

check_bootstrap() {
  local status
  if [ ! -r "$STATUS_FILE" ]; then
    report FAIL "Bootstrap completed" "$STATUS_FILE not found" "$FACILITATOR (see /var/log/workshop-bootstrap.log)"
    return
  fi
  status="$(head -n1 "$STATUS_FILE")"
  case "$status" in
    COMPLETE) report OK "Bootstrap completed" "$STATUS_FILE = COMPLETE" ;;
    BOOTSTRAPPING) report FAIL "Bootstrap completed" "still BOOTSTRAPPING" \
      "Wait a few minutes and rerun. If it does not finish, $FACILITATOR" ;;
    *) report FAIL "Bootstrap completed" "$status" "$FACILITATOR (see /var/log/workshop-bootstrap.log)" ;;
  esac
}

check_env() {
  local missing=()
  [ -n "$STACK_NAME" ] || missing+=(STACK_NAME)
  [ -n "$CLUSTER_NAME" ] || missing+=(CLUSTER_NAME)
  [ -n "$AWS_DEFAULT_REGION" ] || missing+=(AWS_DEFAULT_REGION)
  if [ ${#missing[@]} -gt 0 ]; then
    report FAIL "Shell environment" "unset: ${missing[*]}" \
      "These are set by ~/.bashrc for ec2-user. Run 'sudo su - ec2-user' (note the dash) and rerun."
    return 1
  fi
  if [ "$AWS_DEFAULT_REGION" = "$EXPECTED_REGION" ]; then
    report OK "Region" "$AWS_DEFAULT_REGION"
  else
    report FAIL "Region" "$AWS_DEFAULT_REGION (expected $EXPECTED_REGION)" "$FACILITATOR"
  fi
}

check_tools() {
  local missing=() present=() tool
  for tool in aws git jq kubectl helm python3.11 tmux; do
    if command -v "$tool" > /dev/null 2>&1; then present+=("$tool"); else missing+=("$tool"); fi
  done
  # `sop` is a bash alias in ~/.bashrc; check the module it points at instead.
  if run python3.11 -c 'import amzn_cse_telco_autonomous_network_agents_app.agent.sop_executor' > /dev/null; then
    present+=(sop)
  else
    missing+=(sop)
  fi
  if [ ${#missing[@]} -eq 0 ]; then
    report OK "Tools" "${present[*]}"
  else
    report FAIL "Tools" "missing: ${missing[*]}" "$FACILITATOR (bootstrap log: /var/log/workshop-bootstrap.log)"
  fi
}

STACK_JSON=""
check_stack() {
  local status
  STACK_JSON="$(run aws cloudformation describe-stacks --stack-name "$STACK_NAME" --output json)" || {
    report FAIL "Workshop stack" "cannot describe stack $STACK_NAME" "$FACILITATOR"
    return 1
  }
  status="$(jq -r '.Stacks[0].StackStatus' <<< "$STACK_JSON")"
  case "$status" in
    CREATE_COMPLETE | UPDATE_COMPLETE) report OK "Workshop stack" "$STACK_NAME $status" ;;
    *) report FAIL "Workshop stack" "$STACK_NAME $status" "$FACILITATOR" ;;
  esac
}

check_source_pin() {
  local expected actual
  if [ ! -d "$WORKSHOP_DIR/.git" ]; then
    report FAIL "Source pin" "$WORKSHOP_DIR is not a git checkout" "$FACILITATOR"
    return
  fi
  expected="$(jq -r '.Stacks[0].Outputs[]? | select(.OutputKey=="WorkshopSourceCommit") | .OutputValue' <<< "$STACK_JSON")"
  actual="$(run git -C "$WORKSHOP_DIR" rev-parse HEAD)"
  if [ -z "$expected" ]; then
    report WARN "Source pin" "${actual:0:10} (stack has no WorkshopSourceCommit output)" \
      "Cannot verify against the stack; continue only if the facilitator confirms this revision."
  elif [ "$expected" = "$actual" ]; then
    report OK "Source pin" "${actual:0:10} matches WorkshopSourceCommit"
  else
    report FAIL "Source pin" "checkout ${actual:0:10} != pinned ${expected:0:10}" "$FACILITATOR"
  fi
}

check_cluster() {
  local status version
  status="$(run aws eks describe-cluster --name "$CLUSTER_NAME" --query 'cluster.[status,version]' --output text)" || {
    report FAIL "EKS cluster" "cannot describe $CLUSTER_NAME" "$FACILITATOR"
    return 1
  }
  version="${status#*	}"
  status="${status%%	*}"
  if [ "$status" != "ACTIVE" ]; then
    report FAIL "EKS cluster" "$CLUSTER_NAME is $status" "$FACILITATOR"
    return 1
  fi
  if run kubectl get --raw=/readyz > /dev/null; then
    report OK "EKS cluster reachable" "$CLUSTER_NAME v$version"
  else
    report FAIL "EKS cluster reachable" "$CLUSTER_NAME is ACTIVE but kubectl cannot reach it" \
      "The API endpoint is private: run this on the bastion, not your laptop. Otherwise $FACILITATOR"
    return 1
  fi
}

check_nodes() {
  local desired ready nodegroups ng
  desired=0
  nodegroups="$(run aws eks list-nodegroups --cluster-name "$CLUSTER_NAME" --query 'nodegroups[]' --output text)" || nodegroups=""
  for ng in $nodegroups; do
    desired=$((desired + $(run aws eks describe-nodegroup --cluster-name "$CLUSTER_NAME" --nodegroup-name "$ng" \
      --query 'nodegroup.scalingConfig.desiredSize' --output text || echo 0)))
  done
  ready="$(run kubectl get nodes -o json | jq '[.items[] | select(any(.status.conditions[]; .type=="Ready" and .status=="True"))] | length')" || ready=0
  if [ "$desired" -gt 0 ] && [ "$ready" -ge "$desired" ]; then
    report OK "Worker nodes Ready" "$ready/$desired"
  elif [ "$desired" -eq 0 ]; then
    report FAIL "Worker nodes Ready" "no nodegroup found on $CLUSTER_NAME" "$FACILITATOR"
  else
    report FAIL "Worker nodes Ready" "$ready/$desired" \
      "Nodes can take ~5 min after stack creation; rerun. If still short, $FACILITATOR"
  fi
}

check_addons() {
  local bad=() ok=() ds deploy desired ready avail
  for ds in aws-node kube-proxy; do
    read -r desired ready <<< "$(run kubectl -n kube-system get ds "$ds" \
      -o jsonpath='{.status.desiredNumberScheduled} {.status.numberReady}')" || { bad+=("$ds"); continue; }
    if [ -n "$desired" ] && [ "$desired" = "$ready" ]; then ok+=("$ds"); else bad+=("$ds $ready/$desired"); fi
  done
  for deploy in coredns ebs-csi-controller; do
    avail="$(run kubectl -n kube-system get deploy "$deploy" -o jsonpath='{.status.availableReplicas}')" || avail=""
    if [ "${avail:-0}" -ge 1 ] 2> /dev/null; then ok+=("$deploy"); else bad+=("$deploy ${avail:-0} available"); fi
  done
  if [ ${#bad[@]} -eq 0 ]; then
    report OK "Cluster add-ons healthy" "${ok[*]}"
  else
    report FAIL "Cluster add-ons healthy" "${bad[*]}" "Add-ons settle a few minutes after the nodes join; rerun. If not, $FACILITATOR"
  fi
}

check_helm() {
  # A release stuck in pending-* blocks every later SOP (Helm refuses to act on
  # it). Normal mid-SOP state too, so warn rather than fail.
  local releases pending count
  releases="$(run helm list -a -A -o json)" || {
    report WARN "Helm releases" "helm list failed" "Rerun; if it keeps failing, $FACILITATOR"
    return
  }
  count="$(jq length <<< "$releases")"
  pending="$(jq -r '.[] | select(.status | test("^pending-")) | "\(.namespace)/\(.name) \(.status)"' <<< "$releases" | paste -sd, -)"
  if [ -n "$pending" ]; then
    report WARN "Helm releases" "pending: $pending" \
      "Expected only while an SOP is running in another tmux window. If none is, $FACILITATOR"
  else
    report OK "Helm releases" "$count installed, none pending"
  fi
}

check_bedrock() {
  local out model
  if $SKIP_BEDROCK; then
    report SKIP "Bedrock model access" "--skip-bedrock"
    return
  fi
  # Same probe as the labs: resolve the fast-tier model through the project's
  # resolver, then make the smallest possible Converse call.
  out="$(run timeout "$BEDROCK_TIMEOUT" python3.11 - <<'PY'
import sys
import boto3
from botocore.exceptions import ClientError
from amzn_cse_telco_autonomous_network_agents_app.agent.core.model_resolver import get_model
from amzn_cse_telco_autonomous_network_agents_app.agent.framework.enums import ModelTier

model = get_model(ModelTier.FAST)
print(f"MODEL={model}")
try:
    boto3.client("bedrock-runtime").converse(
        modelId=model,
        messages=[{"role": "user", "content": [{"text": "Reply READY"}]}],
        inferenceConfig={"maxTokens": 4},
    )
except ClientError as exc:
    print(f"ERROR={exc.response['Error']['Code']}: {exc.response['Error']['Message'][:160]}")
    sys.exit(1)
print("BEDROCK_PREFLIGHT_OK")
PY
)"
  local rc=$?
  model="$(sed -n 's/^MODEL=//p' <<< "$out")"
  if [ $rc -eq 0 ] && grep -q BEDROCK_PREFLIGHT_OK <<< "$out"; then
    report OK "Bedrock model access" "${model:-?} in $AWS_DEFAULT_REGION"
  elif [ $rc -eq 124 ]; then
    report FAIL "Bedrock model access" "timed out after ${BEDROCK_TIMEOUT}s" \
      "The first invocation can take ~2 min while model access activates; rerun once. Then $FACILITATOR"
  else
    report FAIL "Bedrock model access" "$(sed -n 's/^ERROR=//p' <<< "$out" | head -n1)" \
      "If AccessDeniedException: wait 2 min and rerun once (access is activating). Then $FACILITATOR"
  fi
}

check_webui() {
  local line name status url
  if $SKIP_WEBUI; then
    report SKIP "Web UI Access stack" "--skip-webui"
    return
  fi
  # Workshop Studio names the stack, so find it by its WebUIUrl output.
  # DescribeStacks without a name needs cloudformation:ListStacks on the role.
  local stacks
  if ! stacks="$(run aws cloudformation describe-stacks --output json)"; then
    report FAIL "Web UI Access stack" "cannot list stacks" \
      "The bastion role lacks cloudformation:ListStacks (template older than this check). $FACILITATOR (or rerun with --skip-webui)"
    return
  fi
  line="$(jq -r '
    .Stacks[] | select(.Outputs[]? | .OutputKey=="WebUIUrl")
    | [.StackName, .StackStatus, (.Outputs[] | select(.OutputKey=="WebUIUrl") | .OutputValue)] | @tsv' <<< "$stacks" | head -n1)"
  if [ -z "$line" ]; then
    report FAIL "Web UI Access stack" "no stack with a WebUIUrl output" \
      "The dashboard sign-in needs it. $FACILITATOR (or rerun with --skip-webui if told the stack is intentionally absent)"
    return
  fi
  IFS=$'\t' read -r name status url <<< "$line"
  case "$status" in
    CREATE_COMPLETE | UPDATE_COMPLETE) report OK "Web UI Access stack" "$name $status ($url)" ;;
    *) report FAIL "Web UI Access stack" "$name $status" "$FACILITATOR" ;;
  esac
}

# ----------------------------------------------------------------------------- main
printf '\nWorkshop readiness check  %s\n\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
log "workshop-check $(date -u +%Y-%m-%dT%H:%M:%SZ) user=$(id -un) host=$(hostname)"

check_user
check_bootstrap
if check_env; then
  check_tools
  if check_stack; then
    check_source_pin
  fi
  if check_cluster; then
    check_nodes
    check_addons
    check_helm
  fi
  check_bedrock
  check_webui
else
  report SKIP "Remaining checks" "environment not set"
fi

echo
{
  printf 'workshop-check %s stack=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "${STACK_NAME:-?}"
  printf '%s\n' "${SUMMARY[@]}"
} > "$RESULT_FILE" 2> /dev/null

if [ "$FAILS" -gt 0 ]; then
  printf '%s%d check(s) FAILED.%s Do not continue until they are resolved. Details: %s\n' "$C_FAIL" "$FAILS" "$C_OFF" "$LOG"
  exit 1
elif [ "$WARNS" -gt 0 ]; then
  printf '%sAll checks passed with %d warning(s).%s You can continue.\n' "$C_WARN" "$WARNS" "$C_OFF"
else
  printf '%sAll checks passed.%s Your environment is ready. Continue to Deploy the 5G Network.\n' "$C_OK" "$C_OFF"
fi
exit 0
