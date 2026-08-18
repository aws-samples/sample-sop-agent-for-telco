# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Tests for ANRA cross-agent tools — trigger_anda_redeploy + watch_anda_deployment_completion."""

from unittest.mock import patch, MagicMock
import pytest

from amzn_cse_telco_autonomous_network_agents_app.agent.agents.anra.tools_cross_agent import (
    trigger_anda_redeploy,
    watch_anda_deployment_completion,
    CROSS_AGENT_TOOLS,
)


class _CmdResult:
    def __init__(self, success=True, stdout="", stderr=""):
        self.success = success
        self.stdout = stdout
        self.stderr = stderr


@patch("amzn_cse_telco_autonomous_network_agents_app.agent.agents.anra.tools_cross_agent.run_cmd")
class TestTriggerAndaRedeploy:
    """Tests for trigger_anda_redeploy tool."""

    def test_creates_cr_and_wakes_anda(self, mock_run):
        mock_run.return_value = _CmdResult(success=True, stdout="created")
        result = trigger_anda_redeploy(
            nf_name="amf", namespace="open5gs", reason="CrashLoopBackOff detected"
        )
        assert "✅ Created DeploymentPlan" in result
        assert "amf" in result
        assert "remediation" in result
        # Two calls: kubectl apply + curl wake
        assert mock_run.call_count == 2

    def test_emergency_priority(self, mock_run):
        mock_run.return_value = _CmdResult(success=True, stdout="created")
        result = trigger_anda_redeploy(
            nf_name="upf", namespace="open5gs",
            reason="UPF crash", priority="emergency"
        )
        assert "emergency" in result.lower() or "Priority: emergency" in result

    def test_cr_creation_failure(self, mock_run):
        mock_run.return_value = _CmdResult(success=False, stderr="forbidden")
        result = trigger_anda_redeploy(
            nf_name="amf", namespace="open5gs", reason="test"
        )
        assert "❌" in result
        assert "Failed to create" in result

    def test_wake_failure_still_succeeds(self, mock_run):
        # CR creation succeeds, wake fails
        mock_run.side_effect = [
            _CmdResult(success=True, stdout="created"),
            _CmdResult(success=False, stderr="connection refused"),
        ]
        result = trigger_anda_redeploy(
            nf_name="nrf", namespace="open5gs", reason="redeploy needed"
        )
        assert "✅ Created DeploymentPlan" in result
        assert "wake failed" in result

    def test_custom_intent_and_vendor(self, mock_run):
        mock_run.return_value = _CmdResult(success=True, stdout="created")
        result = trigger_anda_redeploy(
            nf_name="upf", namespace="open5gs",
            reason="upgrade", intent="upgrade", vendor="nec"
        )
        assert "upgrade" in result.lower() or "Intent: upgrade" in result

    def test_single_quote_in_reason_safe(self, mock_run):
        mock_run.return_value = _CmdResult(success=True, stdout="created")
        result = trigger_anda_redeploy(
            nf_name="amf", namespace="open5gs",
            reason="it's broken; rm -rf /"
        )
        assert "✅ Created DeploymentPlan" in result
        # Verify shlex.quote was used (no raw <<< pattern)
        cmd_arg = mock_run.call_args_list[0][0][0]
        assert "<<<" not in cmd_arg
        assert "echo" in cmd_arg


    def test_plan_name_contains_nf(self, mock_run):
        mock_run.return_value = _CmdResult(success=True, stdout="created")
        result = trigger_anda_redeploy(
            nf_name="smf", namespace="open5gs", reason="test"
        )
        assert "anra-smf-" in result


@patch("amzn_cse_telco_autonomous_network_agents_app.agent.agents.anra.tools_cross_agent.run_cmd")
class TestWatchAndaDeploymentCompletion:
    """Tests for watch_anda_deployment_completion tool."""

    def test_completed_immediately(self, mock_run):
        mock_run.return_value = _CmdResult(success=True, stdout="Completed")
        result = watch_anda_deployment_completion(
            plan_name="anra-amf-123", timeout_seconds=30
        )
        assert "✅" in result
        assert "completed successfully" in result

    def test_failed_status(self, mock_run):
        mock_run.return_value = _CmdResult(success=True, stdout="Failed")
        result = watch_anda_deployment_completion(
            plan_name="anra-amf-123", timeout_seconds=30
        )
        assert "❌" in result
        assert "Failed" in result

    @patch("time.time")
    @patch("time.sleep", MagicMock())
    def test_timeout(self, mock_time, mock_run):
        mock_run.return_value = _CmdResult(success=True, stdout="InProgress")
        mock_time.side_effect = [0, 0, 301]
        result = watch_anda_deployment_completion(
            plan_name="anra-amf-123", timeout_seconds=300
        )
        assert "⏰" in result
        assert "Timed out" in result

    def test_phases_transition(self, mock_run):
        # First call: InProgress, second call: Completed
        mock_run.side_effect = [
            _CmdResult(success=True, stdout="Completed"),
            _CmdResult(success=True, stdout='{"phase":"Completed","nfStatuses":{"amf":"Deployed"}}'),
        ]
        result = watch_anda_deployment_completion(
            plan_name="anra-amf-123", timeout_seconds=30
        )
        assert "✅" in result


class TestCrossAgentToolsList:
    """Verify all tools are exported."""

    def test_all_tools_in_list(self):
        assert len(CROSS_AGENT_TOOLS) == 6
        names = [t.__name__ for t in CROSS_AGENT_TOOLS]
        assert "trigger_anda_redeploy" in names
        assert "watch_anda_deployment_completion" in names
        assert "ask_anpa_provisioning_status" in names
        assert "ask_anda_recent_deployments" in names
