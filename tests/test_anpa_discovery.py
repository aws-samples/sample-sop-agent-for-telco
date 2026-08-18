# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Unit tests for ANPA discovery — Phase 0.1 CRD group + schema fixes,
Phase 0.3 BMC cred env-var fallback."""

import sys
from dataclasses import dataclass
from unittest.mock import patch

import pytest

sys.modules.setdefault("strands", __import__("unittest.mock", fromlist=["MagicMock"]).MagicMock())

from amzn_cse_telco_autonomous_network_agents_app.agent.agents.anpa.discovery import create_hardware_inventory_cr, scan_redfish_endpoints


@dataclass
class FakeCmdResult:
    stdout: str = "hardwareinventory.provisioning.anpa.aws.io/test-host created\n"
    stderr: str = ""
    returncode: int = 0

    @property
    def success(self) -> bool:
        return self.returncode == 0


SAMPLE_HW = {
    "hostname": "test-host",
    "bmc_address": "192.168.30.10",
    "model": "PowerEdge",
    "serial": "7WZ56G4",
    "cpu_cores": 64,
    "memory_gib": 256,
    "interfaces": [
        {"name": "NIC.Integrated.1-1-1", "mac": "aa:bb:cc:dd:ee:01", "speed": 10000},
        {"name": "NIC.Integrated.1-1-2", "mac": "aa:bb:cc:dd:ee:02", "speed": 10000},
    ],
}


def _captured_yaml(mock_run):
    """Extract the YAML body from the tempfile path passed to kubectl apply."""
    # The implementation writes YAML to a tempfile, then run_cmd("kubectl apply -f <path>").
    # We can't read the tempfile after cleanup; instead, intercept the open() call.
    # Simpler: have run_cmd capture the path and read it before cleanup via side_effect.
    cmd = mock_run.call_args[0][0]
    assert cmd.startswith("kubectl apply -f ")
    # Path was deleted by `finally`, but the side_effect captured it
    return mock_run.captured_yaml


@patch("amzn_cse_telco_autonomous_network_agents_app.agent.agents.anpa.discovery.run_cmd")
def test_uses_correct_api_group(mock_run):
    """Regression for Phase 0.1: must emit provisioning.anpa.aws.io, not the old group."""
    captured = {}

    def side_effect(cmd, **_):
        # Read the tempfile before run_cmd's caller deletes it
        path = cmd.split("kubectl apply -f ", 1)[1].strip()
        with open(path) as f:
            captured["yaml"] = f.read()
        return FakeCmdResult()

    mock_run.side_effect = side_effect
    create_hardware_inventory_cr(SAMPLE_HW)
    yaml_body = captured["yaml"]
    assert "apiVersion: provisioning.anpa.aws.io/v1alpha1" in yaml_body
    assert "anpa.eks-hybrid.amazonaws.com" not in yaml_body, (
        "old API group must not appear"
    )


@patch("amzn_cse_telco_autonomous_network_agents_app.agent.agents.anpa.discovery.run_cmd")
def test_no_namespace_in_metadata(mock_run):
    """HardwareInventory is cluster-scoped — namespace must not be set."""
    captured = {}

    def side_effect(cmd, **_):
        path = cmd.split("kubectl apply -f ", 1)[1].strip()
        with open(path) as f:
            captured["yaml"] = f.read()
        return FakeCmdResult()

    mock_run.side_effect = side_effect
    create_hardware_inventory_cr(SAMPLE_HW, namespace="ignored-ns")
    yaml_body = captured["yaml"]
    metadata_block = yaml_body.split("spec:", 1)[0]
    assert "namespace:" not in metadata_block, (
        "cluster-scoped CR must not carry metadata.namespace"
    )


@patch("amzn_cse_telco_autonomous_network_agents_app.agent.agents.anpa.discovery.run_cmd")
def test_schema_fields_match_crd(mock_run):
    """Spec must use schema-correct field names (mac/speed, cpu.cores, memory.totalGiB)."""
    captured = {}

    def side_effect(cmd, **_):
        path = cmd.split("kubectl apply -f ", 1)[1].strip()
        with open(path) as f:
            captured["yaml"] = f.read()
        return FakeCmdResult()

    mock_run.side_effect = side_effect
    create_hardware_inventory_cr(SAMPLE_HW)
    body = captured["yaml"]

    # Required spec fields
    assert "hostname: test-host" in body
    assert "bmcAddress: 192.168.30.10" in body
    assert "cpu:" in body and "cores: 64" in body
    assert "memory:" in body and "totalGiB: 256" in body

    # Interfaces use schema names
    assert "mac: aa:bb:cc:dd:ee:01" in body
    assert "speed:" in body
    # Old (wrong) field names must be gone
    assert "macAddress:" not in body
    assert "speedMbps:" not in body

    # Top-level fields not in CRD schema must be gone (P0.1 schema alignment).
    # NOTE: serialNumber IS in the schema (added in P1.1) — kept here.
    spec_section = body.split("spec:", 1)[1]
    assert "model: PowerEdge" not in spec_section, "spec.model not in CRD schema"
    assert "hardware:" not in spec_section, "spec.hardware nesting not in CRD schema"


@patch("amzn_cse_telco_autonomous_network_agents_app.agent.agents.anpa.discovery.run_cmd")
def test_uses_tempfile_not_stdin(mock_run):
    """Regression: run_cmd doesn't accept stdin_input — must use tempfile + apply -f."""
    mock_run.return_value = FakeCmdResult()
    create_hardware_inventory_cr(SAMPLE_HW)
    # All calls must be `kubectl apply -f <path>`, no stdin_input kwarg
    for call in mock_run.call_args_list:
        args, kwargs = call
        assert args[0].startswith("kubectl apply -f "), (
            f"unexpected cmd: {args[0]!r}"
        )
        assert "stdin_input" not in kwargs


@patch("amzn_cse_telco_autonomous_network_agents_app.agent.agents.anpa.discovery.run_cmd")
def test_kubectl_failure_raises(mock_run):
    mock_run.return_value = FakeCmdResult(stderr="error: forbidden", returncode=1)
    with pytest.raises(RuntimeError, match="kubectl apply failed"):
        create_hardware_inventory_cr(SAMPLE_HW)


@patch("amzn_cse_telco_autonomous_network_agents_app.agent.agents.anpa.discovery.run_cmd")
def test_label_uses_correct_group(mock_run):
    captured = {}

    def side_effect(cmd, **_):
        path = cmd.split("kubectl apply -f ", 1)[1].strip()
        with open(path) as f:
            captured["yaml"] = f.read()
        return FakeCmdResult()

    mock_run.side_effect = side_effect
    create_hardware_inventory_cr(SAMPLE_HW)
    body = captured["yaml"]
    assert 'provisioning.anpa.aws.io/managed: "true"' in body
    assert "anpa.eks-hybrid.amazonaws.com/managed" not in body


# ============================================================================
# Phase 0.3 — BMC credentials default from env when not passed
# ============================================================================


@patch("amzn_cse_telco_autonomous_network_agents_app.agent.util.bmc.curl_bmc")
def test_scan_uses_env_creds_by_default(mock_curl, monkeypatch):
    """scan_redfish_endpoints must default to BMC_USERNAME/BMC_PASSWORD env vars."""
    monkeypatch.setenv("BMC_USERNAME", "admin-from-env")
    monkeypatch.setenv("BMC_PASSWORD", "secret-from-env")
    # Make the scan immediately decide nothing's there (returncode != 0)
    mock_curl.return_value = type(
        "R", (), {"stdout": "", "stderr": "", "returncode": 7, "success": False}
    )()
    # Tiny CIDR keeps the loop bounded
    scan_redfish_endpoints(subnet_cidr="192.0.2.0/30")
    # Env creds are passed to the hardened helper as args, not baked into a command.
    args = mock_curl.call_args_list[0][0]
    assert "admin-from-env" in args and "secret-from-env" in args


@patch("amzn_cse_telco_autonomous_network_agents_app.agent.util.bmc.curl_bmc")
def test_scan_explicit_creds_override_env(mock_curl, monkeypatch):
    """Explicit username/password args win over env vars."""
    monkeypatch.setenv("BMC_USERNAME", "env-user")
    monkeypatch.setenv("BMC_PASSWORD", "env-pass")
    mock_curl.return_value = type(
        "R", (), {"stdout": "", "stderr": "", "returncode": 7, "success": False}
    )()
    scan_redfish_endpoints(
        subnet_cidr="192.0.2.0/30",
        username="explicit-user",
        password="explicit-pass",
    )
    args = mock_curl.call_args_list[0][0]
    assert "explicit-user" in args and "explicit-pass" in args
    assert "env-user" not in args


# ============================================================================
# Phase 1.1 — UUID + serial handoff fields in HardwareInventory CR
# ============================================================================


SAMPLE_HW_WITH_UUID = {
    **SAMPLE_HW,
    "system_uuid": "4c4c4544-0057-5a10-8035-b7c04f364734",
    "cpu_model": "Intel(R) Xeon(R) Platinum 8480+",
    "serial": "7WZ56G4",  # Dell service tag (from Redfish SKU)
}


@patch("amzn_cse_telco_autonomous_network_agents_app.agent.agents.anpa.discovery.run_cmd")
def test_cr_includes_system_uuid(mock_run):
    """Spec must carry systemUUID — the canonical handoff identifier."""
    captured = {}

    def side_effect(cmd, **_):
        path = cmd.split("kubectl apply -f ", 1)[1].strip()
        with open(path) as f:
            captured["yaml"] = f.read()
        return FakeCmdResult()

    mock_run.side_effect = side_effect
    create_hardware_inventory_cr(SAMPLE_HW_WITH_UUID)
    body = captured["yaml"]
    assert "systemUUID: 4c4c4544-0057-5a10-8035-b7c04f364734" in body, (
        "systemUUID must appear in spec for handoff to K8s node systemUUID"
    )


@patch("amzn_cse_telco_autonomous_network_agents_app.agent.agents.anpa.discovery.run_cmd")
def test_cr_includes_serial_number(mock_run):
    captured = {}

    def side_effect(cmd, **_):
        path = cmd.split("kubectl apply -f ", 1)[1].strip()
        with open(path) as f:
            captured["yaml"] = f.read()
        return FakeCmdResult()

    mock_run.side_effect = side_effect
    create_hardware_inventory_cr(SAMPLE_HW_WITH_UUID)
    assert "serialNumber: 7WZ56G4" in captured["yaml"]


@patch("amzn_cse_telco_autonomous_network_agents_app.agent.agents.anpa.discovery.run_cmd")
def test_cr_omits_uuid_gracefully_when_missing(mock_run):
    """Older callers without system_uuid still produce a valid CR."""
    hw_no_uuid = {k: v for k, v in SAMPLE_HW_WITH_UUID.items() if k != "system_uuid"}
    captured = {}

    def side_effect(cmd, **_):
        path = cmd.split("kubectl apply -f ", 1)[1].strip()
        with open(path) as f:
            captured["yaml"] = f.read()
        return FakeCmdResult()

    mock_run.side_effect = side_effect
    create_hardware_inventory_cr(hw_no_uuid)
    body = captured["yaml"]
    # Either omitted or empty — both are valid YAML
    assert "systemUUID:" in body  # field present
    # Just ensure the doc still parses
    import yaml as _yaml
    parsed = _yaml.safe_load(body)
    assert parsed["spec"]["hostname"] == "test-host"


# ============================================================================
# Regression — run_cmd API misuse (caught by live integration test 2026-05-31)
# ============================================================================


def test_no_run_cmd_with_invalid_kwargs():
    """Ensure no caller passes 'check=' or 'stdin_input=' to run_cmd.

    run_cmd's signature is run_cmd(cmd, timeout, shell). 'check' and
    'stdin_input' are not accepted; passing them raises TypeError at
    runtime. P0.1 fixed two such call sites; this test guards against
    a third or any reintroduction.
    """
    import re
    from pathlib import Path

    src = Path(__file__).resolve().parent.parent / "src" / "amzn_cse_telco_autonomous_network_agents_app" / "agent" / "agents" / "anpa" / "discovery.py"
    content = src.read_text()
    bad = re.findall(r"run_cmd\([^)]*\b(check|stdin_input)\s*=", content)
    assert not bad, (
        "discovery.py passes invalid kwargs to run_cmd: " + ", ".join(set(bad))
    )
