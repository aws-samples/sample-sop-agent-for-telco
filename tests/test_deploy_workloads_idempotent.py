"""A second run of 03-deploy-workloads.sh must not change a healthy deployment.

The script is run against stub kubectl/helm binaries that log every call. In a
healthy state it must exit 0 having made only read-only calls; in each unhealthy
state (or with FORCE=1) it must fall through to the install flow.
"""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "free5gc" / "03-deploy-workloads.sh"

pytestmark = pytest.mark.skipif(shutil.which("jq") is None, reason="jq is required by the script")

STUB = """#!/usr/bin/env bash
echo "$(basename "$0") $*" >> "$STUB_LOG"
case "$(basename "$0") $*" in
  "kubectl config current-context") echo test-context ;;
  "kubectl get --raw=/readyz") echo ok ;;
  "helm list -n free5gc -o json") cat "$STUB_DIR/releases.json" ;;
  "kubectl get pods -n free5gc -o json") cat "$STUB_DIR/pods.json" ;;
  "kubectl get pods -n free5gc -l app=packetrusher -o jsonpath="*) printf packetrusher-abc ;;
  "kubectl exec -n free5gc packetrusher-abc -- ip addr show val0000000003") exit "$(cat "$STUB_DIR/ue_rc")" ;;
  # The full flow starts with the namespace apply; stop it at the gtp5g node listing.
  "kubectl get nodes"*) exit 1 ;;
esac
exit 0
"""

READ_ONLY_PREFIXES = (
    "kubectl config current-context",
    "kubectl get ",
    "kubectl exec ",  # only the `ip addr show` probe is reachable on the fast path
    "helm list ",
)

RELEASES = [
    {"name": "free5gc", "chart": "free5gc-0.0.2", "status": "deployed"},
    {"name": "packetrusher", "chart": "packetrusher-0.0.3", "status": "deployed"},
]


def _pod(name, ready=True, phase="Running", owner=None):
    pod = {
        "metadata": {"name": name, "ownerReferences": [{"kind": owner}] if owner else []},
        "status": {"phase": phase, "conditions": [{"type": "Ready", "status": "True" if ready else "False"}]},
    }
    return pod


HEALTHY_PODS = [
    _pod("free5gc-amf-1"),
    _pod("packetrusher-abc"),
    _pod("sub-prov-job-x", ready=False, phase="Succeeded", owner="Job"),
]


def _run(tmp_path, releases=RELEASES, pods=HEALTHY_PODS, ue_rc=0, env_extra=None):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    for tool in ("kubectl", "helm"):
        path = bindir / tool
        path.write_text(STUB)
        path.chmod(0o755)
    (tmp_path / "releases.json").write_text(json.dumps(releases))
    (tmp_path / "pods.json").write_text(json.dumps({"items": pods}))
    (tmp_path / "ue_rc").write_text(str(ue_rc))
    log = tmp_path / "calls.log"
    env = {
        **os.environ,
        "PATH": f"{bindir}:{os.environ['PATH']}",
        "STUB_LOG": str(log),
        "STUB_DIR": str(tmp_path),
        **(env_extra or {}),
    }
    env.pop("NAMESPACE", None)
    env.pop("FORCE", None)
    env.update(env_extra or {})
    result = subprocess.run(["bash", str(SCRIPT)], env=env, capture_output=True, text=True, timeout=60)
    calls = log.read_text().splitlines() if log.exists() else []
    return result, calls


def test_healthy_deployment_is_left_untouched(tmp_path):
    result, calls = _run(tmp_path)
    assert result.returncode == 0, result.stderr
    assert "Nothing was changed" in result.stdout
    mutating = [c for c in calls if not c.startswith(READ_ONLY_PREFIXES)]
    assert mutating == [], mutating


@pytest.mark.parametrize(
    "case",
    [
        {"releases": RELEASES[:1]},
        {"releases": [RELEASES[0], {**RELEASES[1], "chart": "packetrusher-0.0.2"}]},
        {"releases": [RELEASES[0], {**RELEASES[1], "status": "failed"}]},
        {"pods": [_pod("free5gc-upf-1", ready=False), _pod("packetrusher-abc")]},
        {"pods": []},
        {"ue_rc": 1},
        {"env_extra": {"FORCE": "1"}},
    ],
    ids=["release-missing", "chart-version-differs", "release-failed", "pod-not-ready", "no-pods", "no-ue-interface", "force"],
)
def test_unhealthy_or_forced_runs_full_flow(tmp_path, case):
    result, calls = _run(tmp_path, **case)
    assert any(c.startswith("kubectl create namespace free5gc") for c in calls), calls
    assert "Nothing was changed" not in result.stdout
