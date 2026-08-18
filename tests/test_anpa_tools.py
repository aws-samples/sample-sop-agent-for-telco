# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Unit tests for ANPA tools — Phase 0.2 tuple-unpack + list-cmd fixes.

Each PROVISION_TOOL must:
  1. NOT pass a list to run_cmd (run_cmd expects a string).
  2. NOT tuple-unpack run_cmd's CmdResult.
  3. Return a structured tool_result without raising.
"""

import sys
from dataclasses import dataclass
from unittest.mock import patch

import pytest

# strands is stubbed in conftest.py with @tool as a passthrough — no manual setup needed

from amzn_cse_telco_autonomous_network_agents_app.agent.agents.anpa import tools  # noqa: E402
from amzn_cse_telco_autonomous_network_agents_app.agent.agents.anpa.tools import _run  # noqa: E402


@dataclass
class FakeCmdResult:
    stdout: str = ""
    stderr: str = ""
    returncode: int = 0

    @property
    def success(self) -> bool:
        return self.returncode == 0

    @property
    def output(self) -> str:
        return self.stdout + (f"\nSTDERR: {self.stderr}" if self.stderr else "")


class TestRunHelper:
    @patch("amzn_cse_telco_autonomous_network_agents_app.agent.agents.anpa.tools.run_cmd")
    def test_serializes_list_to_quoted_string(self, mock_run):
        mock_run.return_value = FakeCmdResult(stdout="ok", returncode=0)
        out, err, rc = _run(["kubectl", "get", "pods", "-n", "kube system"])
        # The space in 'kube system' must be quoted so shell doesn't split it
        cmd_arg = mock_run.call_args[0][0]
        assert isinstance(cmd_arg, str)
        assert "'kube system'" in cmd_arg
        assert out == "ok" and rc == 0

    @patch("amzn_cse_telco_autonomous_network_agents_app.agent.agents.anpa.tools.run_cmd")
    def test_returns_tuple(self, mock_run):
        mock_run.return_value = FakeCmdResult(stdout="o", stderr="e", returncode=2)
        result = _run(["echo", "hi"])
        assert result == ("o", "e", 2)


class TestProvisionToolsCallable:
    """Each tool must execute end-to-end without raising the previous bugs."""

    @patch("amzn_cse_telco_autonomous_network_agents_app.agent.agents.anpa.tools.run_cmd")
    def test_toggle_provision(self, mock_run):
        mock_run.return_value = FakeCmdResult(stdout="patched", returncode=0)
        result = tools.toggle_provision("srv1", "anpa-test", True)
        assert "success" in result or "status" in result

    @patch("amzn_cse_telco_autonomous_network_agents_app.agent.agents.anpa.tools.run_cmd")
    def test_bump_provision_hash(self, mock_run):
        mock_run.return_value = FakeCmdResult(stdout="patched", returncode=0)
        result = tools.bump_provision_hash("srv1", "anpa-test")
        assert isinstance(result, str)

    @patch("amzn_cse_telco_autonomous_network_agents_app.agent.agents.anpa.tools.run_cmd")
    def test_get_workflow_status(self, mock_run):
        mock_run.return_value = FakeCmdResult(
            stdout='{"status":{"state":"SUCCESS"}}', returncode=0
        )
        result = tools.get_workflow_status("srv1", "tinkerbell")
        assert isinstance(result, str)

    @patch("amzn_cse_telco_autonomous_network_agents_app.agent.agents.anpa.tools.run_cmd")
    def test_get_node_status(self, mock_run):
        mock_run.return_value = FakeCmdResult(
            stdout='{"status":{"conditions":[{"type":"Ready","status":"True"}]}}',
            returncode=0,
        )
        result = tools.get_node_status("srv1")
        assert isinstance(result, str)

    @patch("amzn_cse_telco_autonomous_network_agents_app.agent.agents.anpa.tools.run_cmd")
    def test_create_ssm_activation(self, mock_run):
        mock_run.return_value = FakeCmdResult(
            stdout='{"ActivationId":"a","ActivationCode":"c","ExpirationDate":"x"}',
            returncode=0,
        )
        result = tools.create_ssm_activation("test-cluster", "us-west-1", "node-1")
        assert "ActivationId" in result or "success" in result

    @patch("amzn_cse_telco_autonomous_network_agents_app.agent.agents.anpa.tools.run_cmd")
    def test_drain_and_delete_node(self, mock_run):
        mock_run.return_value = FakeCmdResult(stdout="ok", returncode=0)
        result = tools.drain_and_delete_node("node-1")
        assert isinstance(result, str)

    @patch("amzn_cse_telco_autonomous_network_agents_app.agent.agents.anpa.tools.run_cmd")
    def test_power_cycle_server(self, mock_run):
        mock_run.return_value = FakeCmdResult(stdout="", returncode=0)
        result = tools.power_cycle_server("192.168.30.10")
        assert isinstance(result, str)

    @patch("amzn_cse_telco_autonomous_network_agents_app.agent.agents.anpa.tools.run_cmd")
    def test_get_hardware_health(self, mock_run):
        # First call returns Redfish JSON; subsequent calls also return JSON
        mock_run.return_value = FakeCmdResult(
            stdout='{"Status":{"Health":"OK"}}\n200',
            returncode=0,
        )
        result = tools.get_hardware_health("192.168.30.10")
        assert isinstance(result, str)

    @patch("amzn_cse_telco_autonomous_network_agents_app.agent.agents.anpa.tools.run_cmd")
    def test_ssm_run_command(self, mock_run):
        mock_run.return_value = FakeCmdResult(stdout="cmd-id-123", returncode=0)
        result = tools.ssm_run_command("mi-abc", "echo hi")
        assert isinstance(result, str)


def test_provision_tools_list_complete():
    """Sanity: PROVISION_TOOLS exposes the expected nine tools."""
    names = {t.__name__ for t in tools.PROVISION_TOOLS}
    expected = {
        "toggle_provision", "bump_provision_hash", "get_workflow_status",
        "get_node_status", "create_ssm_activation", "drain_and_delete_node",
        "power_cycle_server", "get_hardware_health", "ssm_run_command",
    }
    assert names == expected
