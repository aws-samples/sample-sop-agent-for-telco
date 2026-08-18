# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Unit tests for cross-agent query tools."""

import sys
from dataclasses import dataclass
from unittest.mock import MagicMock, patch


sys.modules.setdefault("strands", MagicMock())


@dataclass
class FakeCmdResult:
    """Mock for agent.core.executor.CmdResult."""

    success: bool
    output: str
    stdout: str = ""
    stderr: str = ""
    returncode: int = 0

    def __post_init__(self):
        if not self.stdout:
            self.stdout = self.output


class TestAnraCrossAgentTools:
    """Tests for ANRA's cross-agent query tools."""

    @patch("amzn_cse_telco_autonomous_network_agents_app.agent.agents.anra.tools_cross_agent.run_cmd")
    def test_ask_anpa_provisioning_status_success(self, mock_run):
        from amzn_cse_telco_autonomous_network_agents_app.agent.agents.anra.tools_cross_agent import ask_anpa_provisioning_status

        mock_run.return_value = FakeCmdResult(
            success=True,
            output='{"items":[{"name":"worker-003","phase":"Ready"}]}',
        )
        result = ask_anpa_provisioning_status(server_name="worker-003")
        assert "Ready" in result
        assert "worker-003" in mock_run.call_args[0][0]

    @patch("amzn_cse_telco_autonomous_network_agents_app.agent.agents.anra.tools_cross_agent.run_cmd")
    def test_ask_anpa_provisioning_status_unreachable(self, mock_run):
        from amzn_cse_telco_autonomous_network_agents_app.agent.agents.anra.tools_cross_agent import ask_anpa_provisioning_status

        mock_run.return_value = FakeCmdResult(
            success=False, output="", stderr="Connection refused"
        )
        result = ask_anpa_provisioning_status(server_name="worker-003")
        assert "unreachable" in result.lower() or "Connection refused" in result

    @patch("amzn_cse_telco_autonomous_network_agents_app.agent.agents.anra.tools_cross_agent.run_cmd")
    def test_ask_anpa_hardware_inventory(self, mock_run):
        from amzn_cse_telco_autonomous_network_agents_app.agent.agents.anra.tools_cross_agent import ask_anpa_hardware_inventory

        mock_run.return_value = FakeCmdResult(
            success=True,
            output='{"bmcAddress":"10.0.1.5","cpuCount":64}',
        )
        result = ask_anpa_hardware_inventory(server_name="worker-003")
        assert "bmcAddress" in result

    @patch("amzn_cse_telco_autonomous_network_agents_app.agent.agents.anra.tools_cross_agent.run_cmd")
    def test_ask_anda_recent_deployments_no_filter(self, mock_run):
        from amzn_cse_telco_autonomous_network_agents_app.agent.agents.anra.tools_cross_agent import ask_anda_recent_deployments

        mock_run.return_value = FakeCmdResult(
            success=True,
            output='{"plans":[{"name":"smf-upgrade","status":"Completed"}]}',
        )
        result = ask_anda_recent_deployments()
        assert "smf-upgrade" in result
        assert "namespace" not in mock_run.call_args[0][0]

    @patch("amzn_cse_telco_autonomous_network_agents_app.agent.agents.anra.tools_cross_agent.run_cmd")
    def test_ask_anda_recent_deployments_with_namespace(self, mock_run):
        from amzn_cse_telco_autonomous_network_agents_app.agent.agents.anra.tools_cross_agent import ask_anda_recent_deployments

        mock_run.return_value = FakeCmdResult(success=True, output='{"plans":[]}')
        ask_anda_recent_deployments(namespace="core")
        assert "namespace=core" in mock_run.call_args[0][0]

    @patch("amzn_cse_telco_autonomous_network_agents_app.agent.agents.anra.tools_cross_agent.run_cmd")
    def test_ask_anda_deployment_plan_status(self, mock_run):
        from amzn_cse_telco_autonomous_network_agents_app.agent.agents.anra.tools_cross_agent import ask_anda_deployment_plan_status

        mock_run.return_value = FakeCmdResult(
            success=True,
            output='{"name":"upf-rollout","phase":"InProgress"}',
        )
        result = ask_anda_deployment_plan_status(plan_name="upf-rollout")
        assert "InProgress" in result


class TestAnpaCrossAgentTools:
    """Tests for ANPA's cross-agent query tools."""

    @patch("amzn_cse_telco_autonomous_network_agents_app.agent.agents.anpa.tools_cross_agent.run_cmd")
    def test_ask_anra_node_health(self, mock_run):
        from amzn_cse_telco_autonomous_network_agents_app.agent.agents.anpa.tools_cross_agent import ask_anra_node_health

        mock_run.return_value = FakeCmdResult(
            success=True,
            output='{"node":"worker-003","cpu_percent":42,"status":"Ready"}',
        )
        result = ask_anra_node_health(node_name="worker-003")
        assert "Ready" in result
        assert "worker-003" in mock_run.call_args[0][0]

    @patch("amzn_cse_telco_autonomous_network_agents_app.agent.agents.anpa.tools_cross_agent.run_cmd")
    def test_ask_anra_active_alarms_no_filter(self, mock_run):
        from amzn_cse_telco_autonomous_network_agents_app.agent.agents.anpa.tools_cross_agent import ask_anra_active_alarms

        mock_run.return_value = FakeCmdResult(success=True, output='{"alarms":[]}')
        result = ask_anra_active_alarms()
        assert "alarms" in result
        assert "node" not in mock_run.call_args[0][0]

    @patch("amzn_cse_telco_autonomous_network_agents_app.agent.agents.anpa.tools_cross_agent.run_cmd")
    def test_ask_anra_active_alarms_with_node(self, mock_run):
        from amzn_cse_telco_autonomous_network_agents_app.agent.agents.anpa.tools_cross_agent import ask_anra_active_alarms

        mock_run.return_value = FakeCmdResult(success=True, output='{"alarms":[]}')
        ask_anra_active_alarms(node_name="worker-003")
        assert "node=worker-003" in mock_run.call_args[0][0]

    @patch("amzn_cse_telco_autonomous_network_agents_app.agent.agents.anpa.tools_cross_agent.run_cmd")
    def test_ask_anda_workloads_on_node(self, mock_run):
        from amzn_cse_telco_autonomous_network_agents_app.agent.agents.anpa.tools_cross_agent import ask_anda_workloads_on_node

        mock_run.return_value = FakeCmdResult(
            success=True,
            output='{"workloads":["open5gs-amf","srsran-du"]}',
        )
        result = ask_anda_workloads_on_node(node_name="worker-003")
        assert "open5gs-amf" in result


class TestAndaCrossAgentTools:
    """Tests for ANDA's cross-agent query tools."""

    @patch("amzn_cse_telco_autonomous_network_agents_app.agent.agents.anda.tools_cross_agent.run_cmd")
    def test_ask_anra_cluster_health(self, mock_run):
        from amzn_cse_telco_autonomous_network_agents_app.agent.agents.anda.tools_cross_agent import ask_anra_cluster_health

        mock_run.return_value = FakeCmdResult(
            success=True,
            output='{"active_alarms":0,"status":"healthy"}',
        )
        result = ask_anra_cluster_health()
        assert "healthy" in result

    @patch("amzn_cse_telco_autonomous_network_agents_app.agent.agents.anda.tools_cross_agent.run_cmd")
    def test_ask_anra_cluster_health_with_namespace(self, mock_run):
        from amzn_cse_telco_autonomous_network_agents_app.agent.agents.anda.tools_cross_agent import ask_anra_cluster_health

        mock_run.return_value = FakeCmdResult(success=True, output='{}')
        ask_anra_cluster_health(namespace="core")
        assert "namespace=core" in mock_run.call_args[0][0]

    @patch("amzn_cse_telco_autonomous_network_agents_app.agent.agents.anda.tools_cross_agent.run_cmd")
    def test_ask_anpa_node_readiness(self, mock_run):
        from amzn_cse_telco_autonomous_network_agents_app.agent.agents.anda.tools_cross_agent import ask_anpa_node_readiness

        mock_run.return_value = FakeCmdResult(
            success=True,
            output='{"phase":"Ready","hostname":"worker-003"}',
        )
        result = ask_anpa_node_readiness(node_name="worker-003")
        assert "Ready" in result

    @patch("amzn_cse_telco_autonomous_network_agents_app.agent.agents.anda.tools_cross_agent.run_cmd")
    def test_ask_anpa_node_readiness_unreachable(self, mock_run):
        from amzn_cse_telco_autonomous_network_agents_app.agent.agents.anda.tools_cross_agent import ask_anpa_node_readiness

        mock_run.return_value = FakeCmdResult(
            success=False, output="", stderr="timeout"
        )
        result = ask_anpa_node_readiness(node_name="worker-003")
        assert "unreachable" in result.lower() or "timeout" in result
