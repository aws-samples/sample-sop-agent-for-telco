# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Tests for SOP content — validates all SOPs have required sections."""

from pathlib import Path

import pytest

SOP_DIR = Path(__file__).parent.parent / "sops"
ALL_SOPS = [s for s in SOP_DIR.rglob("*.md") if "archive" not in s.relative_to(SOP_DIR).parts]
# Exclude template
REAL_SOPS = [s for s in ALL_SOPS if s.name != "TEMPLATE.md" and "Placeholder" not in s.read_text()[:50]]


class TestSOPStructure:
    @pytest.mark.parametrize("sop_path", REAL_SOPS, ids=lambda p: p.name)
    def test_has_title(self, sop_path):
        content = sop_path.read_text()
        assert content.startswith("# "), f"{sop_path.name} missing title"

    @pytest.mark.parametrize("sop_path", REAL_SOPS, ids=lambda p: p.name)
    def test_has_steps(self, sop_path):
        content = sop_path.read_text()
        assert "## Steps" in content or "### Step" in content, f"{sop_path.name} missing Steps section"

    @pytest.mark.parametrize("sop_path", REAL_SOPS, ids=lambda p: p.name)
    def test_has_bash_blocks(self, sop_path):
        content = sop_path.read_text()
        assert "```bash" in content, f"{sop_path.name} has no executable bash blocks"

    @pytest.mark.parametrize("sop_path", REAL_SOPS, ids=lambda p: p.name)
    def test_has_expected_output(self, sop_path):
        content = sop_path.read_text()
        assert "**Expected**" in content, f"{sop_path.name} missing Expected output markers"

    @pytest.mark.parametrize("sop_path", REAL_SOPS, ids=lambda p: p.name)
    def test_has_prerequisites(self, sop_path):
        content = sop_path.read_text()
        assert "## Prerequisites" in content or "## Prerequisite" in content, f"{sop_path.name} missing Prerequisites"

    @pytest.mark.parametrize("sop_path", [s for s in REAL_SOPS if "day2-remediate" in str(s)], ids=lambda p: p.name)
    def test_day2_has_troubleshooting(self, sop_path):
        content = sop_path.read_text()
        assert "## Troubleshooting" in content, f"{sop_path.name} missing Troubleshooting table"

    @pytest.mark.parametrize("sop_path", [s for s in REAL_SOPS if "day2-remediate" in str(s)], ids=lambda p: p.name)
    def test_day2_has_rollback(self, sop_path):
        content = sop_path.read_text()
        assert "## Rollback" in content, f"{sop_path.name} missing Rollback section"

    @pytest.mark.parametrize("sop_path", [s for s in REAL_SOPS if "day2-remediate" in str(s)], ids=lambda p: p.name)
    def test_day2_has_severity(self, sop_path):
        content = sop_path.read_text()
        assert "**Severity:**" in content, f"{sop_path.name} missing Severity field"


class TestSOPCoverage:
    """The workshop-v3 SOP set (docs/workshop-v3.md). Day-0 is CloudFormation only;
    Day-1 is the Free5GC deploy/validate path; Day-2 are the alarm-bound SOPs."""

    WORKSHOP_SOPS = [
        "day0-infra/provision-free5gc-cloudformation.sop.md",
        "day1-deploy/deploy-free5gc-core.sop.md",
        "day1-deploy/add-subscriber.md",
        "day1-deploy/validate-free5gc-e2e.sop.md",
        "day1-deploy/deploy-free5gc-monitoring-anra.sop.md",
        "day2-remediate/core/free5gc-nf-unavailable.md",
        "day2-remediate/core/free5gc-pod-crashloop.md",
        "day2-remediate/core/free5gc-registration-unavailable.md",
    ]

    @pytest.mark.parametrize("rel", WORKSHOP_SOPS)
    def test_workshop_sop_exists(self, rel):
        assert (SOP_DIR / rel).exists(), f"workshop SOP missing: {rel}"

    def test_day2_sops_exist(self):
        day2 = list((SOP_DIR / "day2-remediate").rglob("*.md"))
        assert len(day2) >= 3, f"Expected >=3 Day 2 SOPs, got {len(day2)}"

    def test_template_exists(self):
        assert (SOP_DIR / "TEMPLATE.md").exists()
