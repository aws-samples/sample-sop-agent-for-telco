#!/bin/bash
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
#
# E2E Test: Run all workshop SOPs in sequence and verify pass/fail
# Usage: ./tests/e2e.sh [--skip-deploy] [--skip-teardown]

set -o pipefail
cd "$(dirname "$0")/.." || exit 1

SKIP_DEPLOY=false
CLEANUP=false
SKIP_TEARDOWN=false
for arg in "$@"; do
  case $arg in
    --skip-deploy) SKIP_DEPLOY=true ;;
    --cleanup) CLEANUP=true ;;
    --skip-teardown) SKIP_TEARDOWN=true ;;
  esac
done

PASS=0
FAIL=0
RESULTS=()

run_sop() {
  local sop="$1"
  local name
  name=$(basename "$sop" .md)
  echo "=========================================="
  echo "SOP: $name"
  echo "=========================================="
  python3.11 -m agent.sop_executor --fix --yes "$sop" 2>&1
  local rc=$?
  if [ $rc -eq 0 ]; then
    PASS=$((PASS + 1))
    RESULTS+=("✅ $name")
  else
    FAIL=$((FAIL + 1))
    RESULTS+=("❌ $name (exit $rc)")
  fi
  return $rc
}

echo "E2E Test Started: $(date -u)"
echo ""

# Day 1: Deploy
if [ "$SKIP_DEPLOY" = false ]; then
  run_sop sops/workshop-deploy/deploy-5g-core.md
  run_sop sops/workshop-deploy/validate-e2e.md
  run_sop sops/workshop-deploy/deploy-monitoring-and-anra.md
fi

# Day 2: Trigger alarm and verify remediation
echo "=========================================="
echo "DAY 2: Trigger alarm + verify remediation"
echo "=========================================="
kubectl exec deploy/anra -n anra -- curl -s -X POST localhost:8080/api/alarms/trigger/core
sleep 35
ALARM_STATUS=$(kubectl logs deploy/anra -n anra --tail=30 2>&1 | grep -c "remediat")
if [ "$ALARM_STATUS" -gt 0 ]; then
  PASS=$((PASS + 1))
  RESULTS+=("✅ day2-remediation-triggered")
else
  FAIL=$((FAIL + 1))
  RESULTS+=("❌ day2-remediation-triggered (no remediation in logs)")
fi

# Summary
echo ""
echo "=========================================="
echo "E2E RESULTS"
echo "=========================================="
for r in "${RESULTS[@]}"; do echo "  $r"; done
echo ""
echo "Pass: $PASS  Fail: $FAIL"
echo "E2E Test Completed: $(date -u)"

[ "$FAIL" -eq 0 ] && exit 0 || exit 1

# Cleanup Helm releases (not infra) for next run
if [ "$CLEANUP" = true ]; then
  echo ""
  echo "=========================================="
  echo "CLEANUP (Helm releases only, keeping EKS)"
  echo "=========================================="
  helm uninstall anra -n anra 2>/dev/null
  helm uninstall ueransim -n srsran 2>/dev/null
  helm uninstall open5gs -n open5gs 2>/dev/null
  kubectl delete ns anra srsran open5gs --ignore-not-found --wait=false
  echo "Cleanup complete — cluster ready for next run"
fi
