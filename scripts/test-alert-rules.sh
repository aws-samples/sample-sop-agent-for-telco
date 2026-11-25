#!/usr/bin/env bash
# Run the promtool unit tests for the workshop alert rules.
# The rules ship as a PrometheusRule custom resource; promtool needs a plain
# rule file, so extract spec.groups into a temporary directory first.
# Requires python3 with PyYAML and either promtool on PATH or Docker.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
WORK="$(mktemp -d)"
trap 'rm -rf "${WORK}"' EXIT
chmod 755 "${WORK}"
mkdir -p "${WORK}/configs/free5gc-monitoring" "${WORK}/tests/promtool"
python3 - "${ROOT}/configs/free5gc-monitoring/free5gc-alert-rules.yaml" \
  "${WORK}/configs/free5gc-monitoring/promtool-rules.yaml" <<'PY'
import sys, yaml
doc = yaml.safe_load(open(sys.argv[1]))
yaml.safe_dump({"groups": doc["spec"]["groups"]}, open(sys.argv[2], "w"))
PY
cp "${ROOT}/tests/promtool/free5gc-alert-rules.test.yaml" "${WORK}/tests/promtool/"
chmod -R a+rX "${WORK}"
cd "${WORK}"
if command -v promtool >/dev/null 2>&1; then
  promtool test rules tests/promtool/free5gc-alert-rules.test.yaml
else
  docker run --rm -v "${WORK}:/w" -w /w --entrypoint promtool prom/prometheus:v3.5.0 \
    test rules tests/promtool/free5gc-alert-rules.test.yaml
fi
