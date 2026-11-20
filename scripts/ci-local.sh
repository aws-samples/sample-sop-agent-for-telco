#!/usr/bin/env bash
# Run the .github/workflows/ci.yml gates locally, before pushing.
#
#   scripts/ci-local.sh          all gates (~1 min, most of it the test suite)
#   scripts/ci-local.sh --fast   static gates only: ruff, bandit, shellcheck, cfn-lint,
#                                bash -n, JSON (seconds); skips unit tests and Helm
#   scripts/ci-local.sh --fix    apply ruff's autofixes and formatting first, then run
#
# Every gate runs even if an earlier one fails; the exit code is non-zero if any failed.
# Tools are installed at the versions ci.yml pins into an isolated venv (.ci-venv/), so the
# result does not depend on what happens to be installed on this machine.
# Note: requirements.txt pins a newer ruff than CI; `ruff` on your PATH is not the CI gate.
#
# KEEP IN SYNC WITH .github/workflows/ci.yml. This script mirrors it; it is not called by it.
# When you change a command or a pinned version there, change it here too.
#
# Differences from CI that remain:
#   - Unit tests run on one Python (PYTHON, default python3); CI runs 3.11 and 3.12.
#   - Helm is whatever `helm` is on PATH; CI pins v3.16.4.
set -uo pipefail

RUFF_VERSION=0.11.12
CFN_LINT_VERSION=1.57.1
PYTHON="${PYTHON:-python3}"

FAST=false
FIX=false
for arg in "$@"; do
  case "$arg" in
    --fast) FAST=true ;;
    --fix) FIX=true ;;
    -h | --help)
      sed -n '2,10p' "$0"
      exit 0
      ;;
    *)
      echo "unknown argument: $arg (use --fast, --fix, --help)" >&2
      exit 2
      ;;
  esac
done

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT" || exit 1
VENV="$REPO_ROOT/.ci-venv"

# ── Two venvs, as in CI: the lint/security jobs install only their tool (ruff at the CI
# pin, which differs from the ruff in requirements.txt), the unit-test job installs
# requirements.txt. Each is rebuilt only when its inputs change. ──
ensure_venv() { # <dir> <stamp-input> <pip args...>
  local dir="$1" stamp
  stamp="$(printf '%s\n%s' "$2" "$("$PYTHON" --version 2>&1)" | sha256sum | cut -c1-16)"
  shift 2
  [ -f "$dir/.stamp-$stamp" ] && return 0
  echo "Preparing $dir ..."
  rm -rf "$dir"
  "$PYTHON" -m venv "$dir" &&
    "$dir/bin/pip" install -q --upgrade pip &&
    "$dir/bin/pip" install -q "$@" &&
    touch "$dir/.stamp-$stamp"
}
TOOLS_PINS=("ruff==$RUFF_VERSION" "cfn-lint==$CFN_LINT_VERSION" bandit shellcheck-py)
ensure_venv "$VENV/tools" "${TOOLS_PINS[*]}" "${TOOLS_PINS[@]}" || exit 1
if ! $FAST; then
  ensure_venv "$VENV/tests" "$(cat requirements.txt) pytest pytest-asyncio pytest-mock" \
    -r requirements.txt pytest pytest-asyncio pytest-mock || exit 1
fi
# Prefer a system shellcheck if present (CI uses the apt package); otherwise the wheel.
export PATH="$PATH:$VENV/tools/bin"
RUFF="$VENV/tools/bin/ruff"
BANDIT="$VENV/tools/bin/bandit"
CFN_LINT="$VENV/tools/bin/cfn-lint"
TEST_PY="$VENV/tests/bin/python"

# ── Gate runner ──
FAILED=()
PASSED=()
SKIPPED=()
gate() {
  local name="$1"
  shift
  printf '\n\033[1m── %s\033[0m\n' "$name"
  if "$@"; then
    PASSED+=("$name")
  else
    FAILED+=("$name")
    printf '\033[31m✗ %s failed\033[0m\n' "$name"
  fi
}
skip() {
  SKIPPED+=("$1 ($2)")
}

if $FIX; then
  printf '\n\033[1m── ruff autofix + format (--fix)\033[0m\n'
  "$RUFF" check src/ tests/ --fix --output-format=concise || true
  "$RUFF" format src/ tests/
fi

# code-quality job
gate "ruff check" "$RUFF" check src/ tests/ --output-format=concise
gate "ruff format --check" "$RUFF" format --check src/ tests/

# security job
gate "bandit" "$BANDIT" -r src/amzn_cse_telco_autonomous_network_agents_app/agent/ \
  -s B602,B603,B404,B607,B104,B110,B112,B107 -ll -q

# CI "shellcheck" job (the first line is advisory in CI: `|| true`; only the second gates)
shellcheck_job() {
  echo "advisory (does not fail the gate):"
  if shellcheck fault-scripts/*.sh fault-scripts/lib/*.sh scripts/*.sh >/dev/null 2>&1; then
    echo "  clean"
  else
    echo "  findings in fault-scripts/ or scripts/*.sh (CI ignores these)"
  fi
  shellcheck scripts/free5gc/*.sh tests/free5gc/run-tests.sh
}
gate "shellcheck" shellcheck_job

# helm-validate job, static part
assets_static() {
  "$CFN_LINT" -t infra/cloudformation/vpc-eks-multus.yaml -i W3005 W3687 W1020 &&
    bash -n scripts/free5gc/*.sh tests/free5gc/run-tests.sh &&
    "$PYTHON" -m json.tool configs/free5gc-monitoring/dashboards/free5gc-core-overview.json >/dev/null
}
gate "cfn-lint + bash -n + dashboard JSON" assets_static

if $FAST; then
  skip "helm" "--fast"
  skip "unit tests" "--fast"
else
  # helm-validate job, Helm part
  if command -v helm >/dev/null 2>&1; then
    helm_job() {
      local chart
      for chart in helm-charts/anra helm-charts/anda helm-charts/anpa helm-charts/ano-platform \
        helm-charts/anra-common helm-charts/ano-topology; do
        # advisory in CI (`|| true`)
        [ -f "$chart/Chart.yaml" ] && { helm lint "$chart/" >/dev/null 2>&1 || echo "  advisory: helm lint $chart has findings"; }
      done
      helm dependency build helm-charts/anra/ >/dev/null &&
        helm template test helm-charts/anra/ --set image.repository=anra --set image.tag=ci >/dev/null &&
        helm lint helm-charts/free5gc-bundle/free5gc-0.0.2.tgz >/dev/null &&
        helm lint helm-charts/free5gc-bundle/packetrusher-0.0.3.tgz >/dev/null &&
        helm template anra helm-charts/anra/ \
          --namespace anra-system \
          --values configs/free5gc-monitoring/anra-values.yaml \
          --set image.repository=anra --set image.tag=ci >/dev/null &&
        echo "helm $(helm version --short 2>/dev/null) (CI pins v3.16.4)"
    }
    gate "helm validate" helm_job
  else
    FAILED+=("helm validate (helm not installed: https://helm.sh/docs/intro/install/)")
  fi

  # unit-tests job
  gate "unit tests ($("$PYTHON" --version 2>&1))" env PYTHONPATH=src "$TEST_PY" -m pytest tests/ -q --tb=short \
    -p no:cacheprovider \
    --ignore=tests/test_adaptive_steering.py \
    --ignore=tests/test_sop_graph.py \
    --ignore=tests/test_sop_nodes.py \
    --ignore=tests/test_graph_conditions.py
fi

# ── Summary ──
printf '\n\033[1m══ ci-local summary\033[0m\n'
[ "${#PASSED[@]}" -gt 0 ] && for g in "${PASSED[@]}"; do printf '  \033[32m✓\033[0m %s\n' "$g"; done
[ "${#SKIPPED[@]}" -gt 0 ] && for g in "${SKIPPED[@]}"; do printf '  - %s skipped\n' "$g"; done
[ "${#FAILED[@]}" -gt 0 ] && for g in "${FAILED[@]}"; do printf '  \033[31m✗\033[0m %s\n' "$g"; done
if [ "${#FAILED[@]}" -gt 0 ]; then
  echo "Not ready to push: ${#FAILED[@]} gate(s) failed."
  exit 1
fi
echo "All gates passed."
