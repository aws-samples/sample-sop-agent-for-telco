#!/usr/bin/env bash
# Lint the agent charts. anpa/anda/anra declare anra-common as an oci://
# dependency that isn't resolvable offline (pre-commit / air-gapped build), so
# we vendor the local copy into each chart's charts/ before linting and remove
# it afterward. stderr is intentionally NOT suppressed — a failing lint must
# show why (previously `2>/dev/null` hid the real error).
set -euo pipefail

COMMON="helm-charts/anra-common"
status=0

for chart in helm-charts/anra helm-charts/anpa helm-charts/anda; do
  [ -d "$chart" ] || continue

  vendored=""
  if [ -d "$COMMON" ] && [ ! -d "$chart/charts/anra-common" ]; then
    mkdir -p "$chart/charts"
    cp -r "$COMMON" "$chart/charts/anra-common"
    vendored="$chart/charts/anra-common"
  fi

  helm lint "$chart" --quiet || status=1

  [ -n "$vendored" ] && rm -rf "$vendored"
done

exit "$status"
