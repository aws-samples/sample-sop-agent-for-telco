# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Helm template rendering tests for the ANPA chart (P0.3 + P0.4)."""

import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
CHART_DIR = REPO_ROOT / "helm-charts" / "anpa"
COMMON_CHART_DIR = REPO_ROOT / "helm-charts" / "anra-common"


@pytest.fixture(scope="module", autouse=True)
def vendor_anra_common():
    """Helm umbrella charts need anra-common copied into charts/ before render."""
    dep_dir = CHART_DIR / "charts" / "anra-common"
    if not dep_dir.exists() and COMMON_CHART_DIR.exists():
        dep_dir.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(str(COMMON_CHART_DIR), str(dep_dir))
    yield
    if dep_dir.exists():
        shutil.rmtree(dep_dir)


def _render(*extra_args):
    if not shutil.which("helm"):
        pytest.skip("helm not installed")
    cmd = [
        "helm",
        "template",
        "anpa",
        str(CHART_DIR),
        "--namespace",
        "anpa-system",
        "--set",
        "image.repository=test",
        # bmc.enabled defaults to false (CI-safe). Most BMC tests need it on,
        # so we enable it here; tests that verify disabled behavior override
        # with --set bmc.enabled=false (last --set wins in Helm).
        "--set",
        "bmc.enabled=true",
        "--set",
        "bmc.username=admin",
        "--set",
        "bmc.password=calvin",
        *extra_args,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        pytest.fail(f"helm template failed: {result.stderr}")
    return result.stdout


class TestAffinity:
    """ANPA defaults to VPC nodes (reaches BMC via VPN). Overridable for hybrid."""

    def test_default_schedules_on_vpc_nodes(self):
        out = _render()
        assert "eks.amazonaws.com/compute-type" in out
        assert "DoesNotExist" in out

    def test_no_affinity_when_overridden_null(self):
        out = _render("--set", "affinity=null")
        assert "eks.amazonaws.com/compute-type" not in out


class TestBmcSecret:
    """P0.3: BMC creds via existingSecret or generated Secret."""

    def test_existing_secret_used_when_set(self):
        out = _render("--set", "bmc.existingSecret=bmc-creds")
        # Deployment must reference the supplied Secret name
        assert "name: bmc-creds" in out
        # And the auto-generated Secret must NOT be emitted
        assert "kind: Secret\nmetadata:\n  name: anpa-secrets" not in out

    def test_secret_generated_when_creds_supplied(self):
        # Creds are now required when bmc.enabled=true and no existingSecret.
        out = _render("--set", "bmc.username=admin", "--set", "bmc.password=calvin")
        # The chart-managed Secret must appear
        assert "kind: Secret" in out
        # The deployment must reference it
        assert "anpa-secrets" in out

    def test_secret_requires_creds_or_existing_secret(self):
        # With bmc.enabled=true (default) and no creds / no existingSecret,
        # the chart must fail fast rather than render an empty Secret.
        # Bypasses the _render helper because that helper does pytest.fail
        # on non-zero exit; this test deliberately wants helm to fail.
        if not shutil.which("helm"):
            pytest.skip("helm not installed")
        import subprocess

        cmd = [
            "helm",
            "template",
            "anpa",
            str(CHART_DIR),
            "--namespace",
            "anpa-system",
            "--set",
            "image.repository=test",
            "--set",
            "bmc.enabled=true",
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, check=False)
        assert result.returncode != 0, "expected helm template to fail without BMC creds"
        assert "bmc.username" in result.stderr or "bmc.password" in result.stderr

    def test_secret_skipped_when_bmc_disabled(self):
        out = _render("--set", "bmc.enabled=false")
        # No chart-managed BMC Secret rendered
        assert "anpa-secrets" not in out or "kind: Secret\nmetadata:\n  name: anpa-secrets" not in out
