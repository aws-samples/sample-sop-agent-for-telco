# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Tests for SOP content — validates all SOPs have required sections."""
from pathlib import Path

import pytest

SOP_DIR = Path(__file__).parent.parent / "sops"
ALL_SOPS = list(SOP_DIR.rglob("*.md"))
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

    @pytest.mark.parametrize("sop_path", [s for s in REAL_SOPS if "day2-remediate" in str(s)],
                             ids=lambda p: p.name)
    def test_day2_has_troubleshooting(self, sop_path):
        content = sop_path.read_text()
        assert "## Troubleshooting" in content, f"{sop_path.name} missing Troubleshooting table"

    @pytest.mark.parametrize("sop_path", [s for s in REAL_SOPS if "day2-remediate" in str(s)],
                             ids=lambda p: p.name)
    def test_day2_has_rollback(self, sop_path):
        content = sop_path.read_text()
        assert "## Rollback" in content, f"{sop_path.name} missing Rollback section"

    @pytest.mark.parametrize("sop_path", [s for s in REAL_SOPS if "day2-remediate" in str(s)],
                             ids=lambda p: p.name)
    def test_day2_has_severity(self, sop_path):
        content = sop_path.read_text()
        assert "**Severity:**" in content, f"{sop_path.name} missing Severity field"


class TestSOPCoverage:
    def test_day0_sops_exist(self):
        day0 = list((SOP_DIR / "day0-infra").glob("*.md"))
        assert len(day0) >= 4, f"Expected >=4 Day 0 SOPs, got {len(day0)}"

    def test_day1_sops_exist(self):
        day1 = list((SOP_DIR / "day1-deploy").glob("*.md"))
        assert len(day1) >= 5, f"Expected >=5 Day 1 SOPs, got {len(day1)}"

    def test_day2_sops_exist(self):
        day2 = list((SOP_DIR / "day2-remediate").rglob("*.md"))
        assert len(day2) >= 5, f"Expected >=5 Day 2 SOPs, got {len(day2)}"

    def test_template_exists(self):
        assert (SOP_DIR / "TEMPLATE.md").exists()
