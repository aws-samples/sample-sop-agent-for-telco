# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Phase 4.1 — diagnosis_tools unit tests."""

import json
from dataclasses import dataclass
from unittest.mock import patch

from amzn_cse_telco_autonomous_network_agents_app.agent.agents.anpa import (
    diagnosis_tools,
)


@dataclass
class FakeR:
    stdout: str = ""
    stderr: str = ""
    returncode: int = 0
    @property
    def success(self) -> bool: return self.returncode == 0


# ----------------------------- get_workflow_logs -----------------------------


WORKFLOW_FAILED_JSON = json.dumps({
    "items": [{
        "metadata": {"name": "provision-server-1-v1"},
        "status": {
            "state": "STATE_FAILED",
            "tasks": [{
                "name": "provision-os",
                "actions": [
                    {"name": "stream-image", "status": "STATE_SUCCESS", "seconds": 120},
                    {"name": "kexec",       "status": "STATE_FAILED",
                     "message": "kexec failed: bad image checksum",
                     "seconds": 5},
                ],
            }],
        },
    }],
})

WORKFLOW_SUCCESS_JSON = json.dumps({
    "items": [{
        "metadata": {"name": "provision-server-1-v1"},
        "status": {
            "state": "STATE_SUCCESS",
            "tasks": [{
                "name": "provision-os",
                "actions": [
                    {"name": "stream-image", "status": "STATE_SUCCESS", "seconds": 110},
                    {"name": "kexec",       "status": "STATE_SUCCESS", "seconds": 8},
                ],
            }],
        },
    }],
})


@patch("amzn_cse_telco_autonomous_network_agents_app.agent.agents.anpa.tools.run_cmd")
def test_get_workflow_logs_extracts_failed_action(mock_run):
    mock_run.return_value = FakeR(stdout=WORKFLOW_FAILED_JSON)
    raw = diagnosis_tools.get_workflow_logs("server-1")
    body = json.loads(raw)
    assert body["state"] == "STATE_FAILED"
    assert len(body["failed_actions"]) == 1
    assert body["failed_actions"][0]["action"] == "kexec"
    assert "bad image checksum" in body["failed_actions"][0]["message"]
    assert len(body["all_actions"]) == 2


@patch("amzn_cse_telco_autonomous_network_agents_app.agent.agents.anpa.tools.run_cmd")
def test_get_workflow_logs_uses_correct_label(mock_run):
    mock_run.return_value = FakeR(stdout=WORKFLOW_SUCCESS_JSON)
    diagnosis_tools.get_workflow_logs("server-1", namespace="tinkerbell")
    cmd = mock_run.call_args[0][0]
    # Must select by `hardware=` label (EKS-H RGD label), not the old ANPA label.
    assert "hardware=server-1" in cmd
    assert "anpa.eks-hybrid.amazonaws.com" not in cmd


@patch("amzn_cse_telco_autonomous_network_agents_app.agent.agents.anpa.tools.run_cmd")
def test_get_workflow_logs_no_match_returns_not_found(mock_run):
    mock_run.return_value = FakeR(stdout=json.dumps({"items": []}))
    raw = diagnosis_tools.get_workflow_logs("missing")
    body = json.loads(raw)
    assert body["status"] == "not_found"


@patch("amzn_cse_telco_autonomous_network_agents_app.agent.agents.anpa.tools.run_cmd")
def test_get_workflow_logs_kubectl_error(mock_run):
    mock_run.return_value = FakeR(stderr="forbidden", returncode=1)
    raw = diagnosis_tools.get_workflow_logs("x")
    body = json.loads(raw)
    assert body["status"] == "error"


# ----------------------------- read_bmc_sel ---------------------------------


SEL_JSON = json.dumps({
    "Members@odata.count": 2,
    "Members": [
        {
            "Id": "1",
            "Created": "2026-01-01T12:00:00Z",
            "Severity": "Critical",
            "Message": "CPU1 thermal trip",
            "SensorType": "Temperature",
            "EntryType": "SEL",
        },
        {
            "Id": "2",
            "Created": "2026-01-02T03:00:00Z",
            "Severity": "OK",
            "Message": "Power cycle",
        },
    ],
})


@patch("amzn_cse_telco_autonomous_network_agents_app.agent.util.bmc.curl_bmc")
def test_read_bmc_sel_returns_entries(mock_run, monkeypatch):
    monkeypatch.setenv("BMC_PASSWORD", "calvin")
    mock_run.return_value = FakeR(stdout=SEL_JSON)
    raw = diagnosis_tools.read_bmc_sel("192.168.30.10", max_entries=10)
    body = json.loads(raw)
    assert body["status"] == "ok"
    assert body["returned"] == 2
    assert any("thermal" in e["message"] for e in body["entries"])


@patch("amzn_cse_telco_autonomous_network_agents_app.agent.util.bmc.curl_bmc")
def test_read_bmc_sel_caps_max_entries(mock_run, monkeypatch):
    monkeypatch.setenv("BMC_PASSWORD", "calvin")
    big = json.dumps({"Members": [{"Id": str(i), "Message": f"e{i}"} for i in range(50)]})
    mock_run.return_value = FakeR(stdout=big)
    raw = diagnosis_tools.read_bmc_sel("192.168.30.10", max_entries=5)
    body = json.loads(raw)
    assert body["returned"] == 5


@patch("amzn_cse_telco_autonomous_network_agents_app.agent.util.bmc.curl_bmc")
def test_read_bmc_sel_unreachable(mock_run):
    mock_run.return_value = FakeR(returncode=7)
    raw = diagnosis_tools.read_bmc_sel("10.0.0.1")
    body = json.loads(raw)
    assert body["status"] == "unavailable"


# ----------------------------- inspect_node_join ----------------------------


@patch("amzn_cse_telco_autonomous_network_agents_app.agent.agents.anpa.diagnosis_tools._run")
def test_inspect_node_join_node_exists_and_ready(mock_run):
    node = {"status": {
        "conditions": [{"type": "Ready", "status": "True"}],
        "nodeInfo": {"kubeletVersion": "v1.31.0", "systemUUID": "uuid-1"},
    }}
    mock_run.side_effect = [
        (json.dumps(node), "", 0),  # kubectl get node
        (json.dumps({"InstanceInformationList": [{"PingStatus": "Online"}]}), "", 0),  # ssm
        (json.dumps({"spec": {"systemUUID": "uuid-1", "bmcAddress": "10.1"}, "status": {"phase": "Provisioned"}}), "", 0),  # hwi
        (json.dumps({"items": []}), "", 0),  # events
    ]
    raw = diagnosis_tools.inspect_node_join("mi-test")
    body = json.loads(raw)
    assert body["node"]["exists"] is True
    assert body["node"]["ready"] == "True"
    assert body["ssm"]["managed_instances"] == 1
    assert body["hardware_inventory"]["exists"] is True


@patch("amzn_cse_telco_autonomous_network_agents_app.agent.agents.anpa.diagnosis_tools._run")
def test_inspect_node_join_node_missing(mock_run):
    mock_run.side_effect = [
        ("", "", 0),  # node not found
        ("", "", 1),  # ssm fails
        ("", "", 0),  # hwi missing
    ]
    raw = diagnosis_tools.inspect_node_join("ghost")
    body = json.loads(raw)
    assert body["node"]["exists"] is False


def test_diagnosis_tools_registry_complete():
    names = {t.__name__ for t in diagnosis_tools.DIAGNOSIS_TOOLS}
    assert names == {"get_workflow_logs", "read_bmc_sel", "inspect_node_join"}
