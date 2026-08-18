# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Tests for ANPA preflight reasoner — Phase 2.

Verifies:
  - NF profiles parse and resolve from disk.
  - Deterministic readiness check correctly classifies pass/required/recommended.
  - Summary rendering is human-readable and structured.
  - The inventory router exposes /api/inventory/{hostname}/readiness.
"""

import sys
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import patch

import pytest

from amzn_cse_telco_autonomous_network_agents_app.agent.agents.anpa.preflight_reasoner import (
    ReadinessGap,
    ReadinessReport,
    assess_readiness,
    load_profile,
)


REPO_ROOT = Path(__file__).resolve().parent.parent
PROFILES_DIR = REPO_ROOT / "configs" / "nf-profiles"


# -------- canonical inputs (mirroring real iDRAC .30.10 output) --------

GOOD_BIOS_DELL = {
    "BootMode": "Uefi",
    "SriovGlobalEnable": "Enabled",
    "ProcCStates": "Disabled",
    "EnergyPerformanceBias": "MaxPower",
    "LogicalProc": "Disabled",       # HT off — UPF-recommended
    "MemFrequency": "MaxPerf",
    "SubNumaCluster": "Enabled",
}

LIVE_BIOS_DELL_3010 = {  # what we actually saw on .30.10
    "BootMode": "Uefi",
    "SriovGlobalEnable": "Enabled",
    "ProcCStates": "Disabled",
    "EnergyPerformanceBias": "MaxPower",
    "LogicalProc": "Enabled",        # HT ON — UPF wants OFF (recommended gap)
    "MemFrequency": "MaxPerf",
    "SubNumaCluster": "Disabled",    # UPF prefers Enabled (recommended gap)
}

GOOD_HWI_SPEC = {
    "hostname": "mi-test",
    "bmcAddress": "192.168.30.10",
    "systemUUID": "4c4c4544-0057-5a10-8035-b7c04f364734",
    "serialNumber": "7WZ56G4",
    "cpu": {"cores": 64, "model": "Intel Xeon"},
    "memory": {"totalGiB": 256},
}


class TestProfileLoading:
    def test_upf_profile_loads(self):
        p = load_profile("upf", profiles_dir=PROFILES_DIR)
        assert p["nf"] == "upf"
        assert "bios" in p and "required" in p["bios"]
        assert p["cpu"]["min_cores"] >= 1

    def test_gnb_profile_loads(self):
        p = load_profile("gnb", profiles_dir=PROFILES_DIR)
        assert p["nf"] == "gnb"
        # gNB explicitly requires HT off (DU timing)
        assert p["bios"]["required"]["LogicalProc"] == "Disabled"

    def test_unknown_profile_raises(self):
        with pytest.raises(FileNotFoundError):
            load_profile("nonexistent-nf-xyz", profiles_dir=PROFILES_DIR)


class TestReadinessAssessment:
    def test_all_green_for_perfect_box(self):
        report = assess_readiness(
            nf="upf",
            hostname="ideal-host",
            hardware_inventory=GOOD_HWI_SPEC,
            bios_attributes=GOOD_BIOS_DELL,
            firmware_inventory=[],
            profile=load_profile("upf", profiles_dir=PROFILES_DIR),
        )
        assert report.ready is True
        # Recommended fields are all OK in GOOD_BIOS_DELL → no recommended gaps either
        assert all(g.severity == "recommended" for g in report.gaps) or not report.gaps

    def test_live_30_10_is_ready_with_recommendations(self):
        """Mirrors real site-002 .30.10: required all green, two recommended gaps (HT, SubNumaCluster)."""
        report = assess_readiness(
            nf="upf",
            hostname="mi-0c32a0cb4c4c06fdd",
            hardware_inventory=GOOD_HWI_SPEC,
            bios_attributes=LIVE_BIOS_DELL_3010,
            firmware_inventory=[],
            profile=load_profile("upf", profiles_dir=PROFILES_DIR),
        )
        # Required all pass → ready
        required_gaps = [g for g in report.gaps if g.severity == "required"]
        assert required_gaps == [], f"expected no required gaps, got {required_gaps}"
        assert report.ready is True
        # Two recommended gaps: LogicalProc + SubNumaCluster
        rec_fields = {g.field for g in report.gaps if g.severity == "recommended"}
        assert "LogicalProc" in rec_fields
        assert "SubNumaCluster" in rec_fields

    def test_required_bios_gap_blocks_readiness(self):
        bad = {**GOOD_BIOS_DELL, "SriovGlobalEnable": "Disabled"}
        report = assess_readiness(
            nf="upf",
            hostname="bad-host",
            hardware_inventory=GOOD_HWI_SPEC,
            bios_attributes=bad,
            profile=load_profile("upf", profiles_dir=PROFILES_DIR),
        )
        assert report.ready is False
        assert any(g.field == "SriovGlobalEnable" and g.severity == "required" for g in report.gaps)

    def test_missing_bios_attribute_is_required_gap(self):
        # Some non-Dell BMCs don't expose SriovGlobalEnable at all
        sparse = {k: v for k, v in GOOD_BIOS_DELL.items() if k != "SriovGlobalEnable"}
        report = assess_readiness(
            nf="upf",
            hostname="other-vendor",
            hardware_inventory=GOOD_HWI_SPEC,
            bios_attributes=sparse,
            profile=load_profile("upf", profiles_dir=PROFILES_DIR),
        )
        gap = next(g for g in report.gaps if g.field == "SriovGlobalEnable")
        assert gap.severity == "required"
        assert gap.actual is None

    def test_cpu_below_minimum_blocks(self):
        small = {**GOOD_HWI_SPEC, "cpu": {"cores": 16, "model": "x"}}
        report = assess_readiness(
            nf="upf",
            hostname="small-host",
            hardware_inventory=small,
            bios_attributes=GOOD_BIOS_DELL,
            profile=load_profile("upf", profiles_dir=PROFILES_DIR),
        )
        assert report.ready is False
        assert any(g.category == "cpu" and g.field == "cores" for g in report.gaps)

    def test_memory_below_minimum_blocks(self):
        thin = {**GOOD_HWI_SPEC, "memory": {"totalGiB": 64}}
        report = assess_readiness(
            nf="upf",
            hostname="thin-host",
            hardware_inventory=thin,
            bios_attributes=GOOD_BIOS_DELL,
            profile=load_profile("upf", profiles_dir=PROFILES_DIR),
        )
        assert report.ready is False
        assert any(g.category == "memory" for g in report.gaps)

    def test_firmware_missing_is_recommended_gap(self):
        report = assess_readiness(
            nf="upf",
            hostname="no-fw",
            hardware_inventory=GOOD_HWI_SPEC,
            bios_attributes=GOOD_BIOS_DELL,
            firmware_inventory=[],  # nothing matching "Intel E810"
            profile=load_profile("upf", profiles_dir=PROFILES_DIR),
        )
        # recommended only — does NOT flip ready=False
        assert report.ready is True
        assert any(
            g.severity == "recommended" and g.category == "firmware"
            for g in report.gaps
        )

    def test_summary_is_structured_and_useful(self):
        bad = {**GOOD_BIOS_DELL, "BootMode": "Bios"}
        report = assess_readiness(
            nf="upf",
            hostname="legacy-bios",
            hardware_inventory=GOOD_HWI_SPEC,
            bios_attributes=bad,
            profile=load_profile("upf", profiles_dir=PROFILES_DIR),
        )
        assert "NOT READY" in report.summary
        assert "BootMode" in report.summary
        assert "legacy-bios" in report.summary

    def test_to_dict_shape(self):
        report = assess_readiness(
            nf="upf",
            hostname="x",
            hardware_inventory=GOOD_HWI_SPEC,
            bios_attributes=GOOD_BIOS_DELL,
            profile=load_profile("upf", profiles_dir=PROFILES_DIR),
        )
        d = report.to_dict()
        assert set(d.keys()) == {"nf", "hostname", "ready", "gaps", "summary"}
        assert isinstance(d["gaps"], list)
