# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Tests for ANPA reconciler — Phase 5.2 emit_baremetal_provision_cr.

Per ADR-0001 (revised), ANPA's autonomous flow emits the real EKS-H
BareMetalProvision CR (25-field schema from
day0/.../bare-metal-kro/provision-rgd.yaml) directly, treating the CRD
as EKS-H's API. These tests assert:

  1. Every required field of the 25-field schema is emitted.
  2. Discovery-derived fields come from HardwareInventory.
  3. Intent fields (cluster, profile, tuning) come from the spec.
  4. Missing HardwareInventory raises clearly.
  5. Missing MAC raises clearly (preflight gate failure).
  6. Multi-node ProvisioningRequests emit one CR per node.
  7. CR is applied via kubectl apply (not just generated).
"""
import json
from unittest.mock import patch, MagicMock

import pytest

# 25 fields from day0/.../bare-metal-kro/provision-rgd.yaml — the canonical
# schema EKS-H's bare-metal-kro RGD watches. This is the contract surface
# between ANPA and EKS-H.
EKS_H_PROVISION_FIELDS = {
    "name", "mac", "ip", "machineProfile", "osProfile",
    "destDisk", "efiPartition", "rootPartition",
    "kernelPath", "initrdPath",
    "osArchive", "osArchiveType", "osArchiveChecksum", "osFsType",
    "gateway", "netmaskCIDR", "dnsServers",
    "serverGroup", "namespace", "provisionHash",
    "clusterName", "clusterRegion", "hybridNodesRole",
    "tuningKernelCmdline", "tuningSysctl", "tuningDisabledServices",
}


def _ok(stdout="", stderr="", returncode=0):
    """Build a CmdResult-shaped success."""
    r = MagicMock()
    r.stdout = stdout
    r.stderr = stderr
    r.returncode = returncode
    r.success = (returncode == 0)
    return r


def _hwi_json(name="dell-r760-001", mac="aa:bb:cc:dd:ee:01"):
    """A representative HardwareInventory-like JSON, as kubectl get -o json prints."""
    return json.dumps({
        "apiVersion": "provisioning.anpa.aws.io/v1alpha1",
        "kind": "HardwareInventory",
        "metadata": {"name": name},
        "spec": {
            "hostname": name,
            "bmcAddress": "192.168.30.10",
            "systemUUID": "4c4c4544-0057-5a10-8035-b7c04f364734",
            "serialNumber": "7WZ56G4",
            "interfaces": [
                {"name": "eno1", "mac": mac},
                {"name": "eno2", "mac": "aa:bb:cc:dd:ee:02"},
            ],
        },
    })


@pytest.fixture
def base_spec():
    """A minimal ProvisioningRequest spec representing operator/policy intent."""
    return {
        "clusterName": "site-002-workload",
        "clusterRegion": "us-west-1",
        "groupName": "upf-pool-1",
        "machineProfile": "poweredge-xr8000r-2disk",
        "osProfile": "ubuntu-noble",
        "osArchive": "https://images.example.com/ubuntu-noble.tar.gz",
        "osArchiveChecksum": "sha256:abc123",
        "gateway": "192.168.40.1",
        "netmaskCIDR": "/24",
        "dnsServers": "192.168.40.53",
        "tuningKernelCmdline": "isolcpus=2-31,34-63",
        "tuningSysctl": "vm.swappiness=0",
        "tuningDisabledServices": "irqbalance",
        "bareMetalNamespace": "tinkerbell",
        "nodes": [
            {"hostname": "dell-r760-001", "ip": "192.168.40.11", "role": "worker"},
        ],
    }


def _capture_apply_yaml(spec_capture: dict):
    """Build a run_cmd side_effect that captures the YAML written to the apply file."""
    def _se(cmd, **kw):
        if cmd.startswith("kubectl get hardwareinventory"):
            return _ok(stdout=_hwi_json())
        if cmd.startswith("kubectl apply -f "):
            yaml_path = cmd.split("kubectl apply -f ", 1)[1].strip()
            with open(yaml_path) as f:
                spec_capture["yaml"] = f.read()
            return _ok()
        return _ok()
    return _se


# -------- happy-path: the CR has every EKS-H field at the right values --------

def test_emit_includes_every_eks_h_field(base_spec):
    from amzn_cse_telco_autonomous_network_agents_app.agent.agents.anpa import reconciler

    captured: dict = {}
    with patch.object(reconciler, "run_cmd", side_effect=_capture_apply_yaml(captured)):
        reconciler._emit_baremetal_provision_cr("upf-req-1", "anpa-system", base_spec)

    yaml_text = captured["yaml"]
    # Every field from the EKS-H schema must appear as a key in the rendered CR.
    for field in EKS_H_PROVISION_FIELDS:
        assert f"  {field}:" in yaml_text, f"missing field {field!r} in emitted CR"


def test_emit_uses_hardwareinventory_mac(base_spec):
    """Discovery-derived MAC comes from HardwareInventory, not the spec."""
    from amzn_cse_telco_autonomous_network_agents_app.agent.agents.anpa import reconciler

    captured: dict = {}
    with patch.object(reconciler, "run_cmd", side_effect=_capture_apply_yaml(captured)):
        reconciler._emit_baremetal_provision_cr("upf-req-1", "anpa-system", base_spec)

    assert 'mac: "aa:bb:cc:dd:ee:01"' in captured["yaml"], "MAC should come from HWI eno1, not the spec"


def test_emit_uses_intent_ip_and_cluster(base_spec):
    """Per-node IP from intent; cluster fields from request spec."""
    from amzn_cse_telco_autonomous_network_agents_app.agent.agents.anpa import reconciler

    captured: dict = {}
    with patch.object(reconciler, "run_cmd", side_effect=_capture_apply_yaml(captured)):
        reconciler._emit_baremetal_provision_cr("upf-req-1", "anpa-system", base_spec)

    assert 'ip: "192.168.40.11"' in captured["yaml"]
    assert "clusterName: site-002-workload" in captured["yaml"]
    assert "clusterRegion: us-west-1" in captured["yaml"]
    assert "hybridNodesRole: worker" in captured["yaml"]


def test_emit_includes_tuning_fields(base_spec):
    """Tuning fields wired through unchanged for the RGD's tuning stage."""
    from amzn_cse_telco_autonomous_network_agents_app.agent.agents.anpa import reconciler

    captured: dict = {}
    with patch.object(reconciler, "run_cmd", side_effect=_capture_apply_yaml(captured)):
        reconciler._emit_baremetal_provision_cr("upf-req-1", "anpa-system", base_spec)

    assert 'tuningKernelCmdline: "isolcpus=2-31,34-63"' in captured["yaml"]
    assert 'tuningSysctl: "vm.swappiness=0"' in captured["yaml"]
    assert 'tuningDisabledServices: "irqbalance"' in captured["yaml"]


def test_emit_targets_eks_h_namespace_and_marks_ownership(base_spec):
    """CR goes into the namespace EKS-H's bare-metal-kro RGD watches; ANPA labels mark ownership."""
    from amzn_cse_telco_autonomous_network_agents_app.agent.agents.anpa import reconciler

    captured: dict = {}
    with patch.object(reconciler, "run_cmd", side_effect=_capture_apply_yaml(captured)):
        reconciler._emit_baremetal_provision_cr("upf-req-1", "anpa-system", base_spec)

    assert "namespace: tinkerbell" in captured["yaml"]
    assert "provisioning.anpa.aws.io/managed: \"true\"" in captured["yaml"]
    assert "provisioning.anpa.aws.io/provisioning-request: upf-req-1" in captured["yaml"]


def test_emit_uses_kro_run_apiversion(base_spec):
    """The CR must use kro.run/v1alpha1 — that's the EKS-H bare-metal-kro RGD's group."""
    from amzn_cse_telco_autonomous_network_agents_app.agent.agents.anpa import reconciler

    captured: dict = {}
    with patch.object(reconciler, "run_cmd", side_effect=_capture_apply_yaml(captured)):
        reconciler._emit_baremetal_provision_cr("upf-req-1", "anpa-system", base_spec)

    assert "apiVersion: kro.run/v1alpha1" in captured["yaml"]
    assert "kind: BareMetalProvision" in captured["yaml"]


# -------- multi-node and edge cases --------

def test_emit_one_cr_per_node(base_spec):
    """A multi-node ProvisioningRequest emits one CR per node."""
    from amzn_cse_telco_autonomous_network_agents_app.agent.agents.anpa import reconciler

    base_spec["nodes"] = [
        {"hostname": "dell-r760-001", "ip": "192.168.40.11", "role": "worker"},
        {"hostname": "dell-r760-002", "ip": "192.168.40.12", "role": "worker"},
    ]

    apply_count = {"n": 0}

    def _se(cmd, **kw):
        if cmd.startswith("kubectl get hardwareinventory"):
            host = cmd.split()[-3]  # the resource name
            return _ok(stdout=_hwi_json(name=host, mac="aa:bb:cc:dd:ee:99"))
        if cmd.startswith("kubectl apply -f "):
            apply_count["n"] += 1
            return _ok()
        return _ok()

    with patch.object(reconciler, "run_cmd", side_effect=_se):
        reconciler._emit_baremetal_provision_cr("upf-req-1", "anpa-system", base_spec)

    assert apply_count["n"] == 2, "expected one apply per node"


def test_emit_raises_on_missing_hardwareinventory(base_spec):
    """If preflight passed but HWI vanished, surface the bug clearly."""
    from amzn_cse_telco_autonomous_network_agents_app.agent.agents.anpa import reconciler

    def _se(cmd, **kw):
        if cmd.startswith("kubectl get hardwareinventory"):
            return _ok(stdout="")  # --ignore-not-found returns empty
        return _ok()

    with patch.object(reconciler, "run_cmd", side_effect=_se):
        with pytest.raises(RuntimeError, match="HardwareInventory.*not found"):
            reconciler._emit_baremetal_provision_cr("upf-req-1", "anpa-system", base_spec)


def test_emit_raises_when_hwi_has_no_mac(base_spec):
    """Discovery should always produce at least one MAC; if not, fail loudly."""
    from amzn_cse_telco_autonomous_network_agents_app.agent.agents.anpa import reconciler

    hwi_no_mac = json.dumps({
        "spec": {"hostname": "dell-r760-001", "interfaces": [{"name": "eno1"}]}
    })

    def _se(cmd, **kw):
        if cmd.startswith("kubectl get hardwareinventory"):
            return _ok(stdout=hwi_no_mac)
        return _ok()

    with patch.object(reconciler, "run_cmd", side_effect=_se):
        with pytest.raises(RuntimeError, match="no MAC"):
            reconciler._emit_baremetal_provision_cr("upf-req-1", "anpa-system", base_spec)


def test_emit_raises_on_kubectl_apply_failure(base_spec):
    """Surface kubectl apply errors as RuntimeError (so reconciler can retry)."""
    from amzn_cse_telco_autonomous_network_agents_app.agent.agents.anpa import reconciler

    def _se(cmd, **kw):
        if cmd.startswith("kubectl get hardwareinventory"):
            return _ok(stdout=_hwi_json())
        if cmd.startswith("kubectl apply -f "):
            return _ok(stderr="rejected by RGD: invalid osArchive", returncode=1)
        return _ok()

    with patch.object(reconciler, "run_cmd", side_effect=_se):
        with pytest.raises(RuntimeError, match="Failed to apply BareMetalProvision"):
            reconciler._emit_baremetal_provision_cr("upf-req-1", "anpa-system", base_spec)


# ===========================================================================
# MAC lowercasing regression tests (dlupescu feedback on CR-282837788)
# ===========================================================================

from amzn_cse_telco_autonomous_network_agents_app.agent.agents.anpa import reconciler


@patch.dict("os.environ", {"BMC_USERNAME": "admin", "BMC_PASSWORD": "secret"})
@patch("amzn_cse_telco_autonomous_network_agents_app.agent.agents.anpa.reconciler.run_cmd")
def test_mac_is_lowercased_in_inventory_cr(mock_run_cmd, base_spec):
    """Ensure uppercase MACs from HardwareInventory are lowercased in BareMetalInventory CR."""
    spec_capture = {}

    def _se(cmd, **kw):
        if cmd.startswith("kubectl get hardwareinventory"):
            # Return UPPERCASE MAC to verify lowercasing
            return _ok(stdout=_hwi_json(mac="AA:BB:CC:DD:EE:FF"))
        if cmd.startswith("kubectl apply -f "):
            yaml_path = cmd.split("kubectl apply -f ", 1)[1].strip()
            with open(yaml_path) as f:
                spec_capture["yaml"] = f.read()
            return _ok()
        return _ok()

    mock_run_cmd.side_effect = _se
    reconciler._emit_baremetal_inventory_cr("req-1", "default", base_spec)

    assert "aa:bb:cc:dd:ee:ff" in spec_capture["yaml"]
    assert "AA:BB:CC:DD:EE:FF" not in spec_capture["yaml"]


@patch.dict("os.environ", {"BMC_USERNAME": "admin", "BMC_PASSWORD": "secret"})
@patch("amzn_cse_telco_autonomous_network_agents_app.agent.agents.anpa.reconciler.run_cmd")
def test_mac_is_lowercased_in_provision_cr(mock_run_cmd, base_spec):
    """Ensure uppercase MACs from HardwareInventory are lowercased in BareMetalProvision CR."""
    spec_capture = {}

    def _se(cmd, **kw):
        if cmd.startswith("kubectl get hardwareinventory"):
            return _ok(stdout=_hwi_json(mac="AA:BB:CC:DD:EE:FF"))
        if cmd.startswith("kubectl apply -f "):
            yaml_path = cmd.split("kubectl apply -f ", 1)[1].strip()
            with open(yaml_path) as f:
                spec_capture["yaml"] = f.read()
            return _ok()
        return _ok()

    mock_run_cmd.side_effect = _se
    reconciler._emit_baremetal_provision_cr("req-1", "default", base_spec)

    assert "aa:bb:cc:dd:ee:ff" in spec_capture["yaml"]
    assert "AA:BB:CC:DD:EE:FF" not in spec_capture["yaml"]


# ===========================================================================
# BMC credential validation tests (dlupescu feedback on CR-282837788)
# ===========================================================================


@patch.dict("os.environ", {"BMC_USERNAME": "", "BMC_PASSWORD": ""}, clear=False)
@patch("amzn_cse_telco_autonomous_network_agents_app.agent.agents.anpa.reconciler.run_cmd")
def test_emit_inventory_fails_when_bmc_credentials_missing(mock_run_cmd, base_spec):
    """RuntimeError raised before any kubectl call if BMC env vars are empty."""
    with pytest.raises(RuntimeError, match="BMC_USERNAME and BMC_PASSWORD"):
        reconciler._emit_baremetal_inventory_cr("req-1", "default", base_spec)

    mock_run_cmd.assert_not_called()


@patch.dict("os.environ", {"BMC_USERNAME": "admin", "BMC_PASSWORD": ""}, clear=False)
@patch("amzn_cse_telco_autonomous_network_agents_app.agent.agents.anpa.reconciler.run_cmd")
def test_emit_inventory_fails_when_bmc_password_missing(mock_run_cmd, base_spec):
    """RuntimeError raised when only BMC_PASSWORD is empty."""
    with pytest.raises(RuntimeError, match="BMC_USERNAME and BMC_PASSWORD"):
        reconciler._emit_baremetal_inventory_cr("req-1", "default", base_spec)

    mock_run_cmd.assert_not_called()


@patch.dict("os.environ", {"BMC_USERNAME": "", "BMC_PASSWORD": "secret"}, clear=False)
@patch("amzn_cse_telco_autonomous_network_agents_app.agent.agents.anpa.reconciler.run_cmd")
def test_emit_inventory_fails_when_bmc_username_missing(mock_run_cmd, base_spec):
    """RuntimeError raised when only BMC_USERNAME is empty."""
    with pytest.raises(RuntimeError, match="BMC_USERNAME and BMC_PASSWORD"):
        reconciler._emit_baremetal_inventory_cr("req-1", "default", base_spec)

    mock_run_cmd.assert_not_called()
