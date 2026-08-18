# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Unit tests for ANPA AI failure handler."""

import sys
from unittest.mock import MagicMock, patch


sys.modules.setdefault("strands", MagicMock())

from amzn_cse_telco_autonomous_network_agents_app.agent.agents.anpa.failure_handler import handle_provisioning_failure


class TestFailureHandler:
    """Tests for handle_provisioning_failure."""

    @patch("amzn_cse_telco_autonomous_network_agents_app.agent.agents.anpa.failure_handler.Agent")
    def test_invokes_agent_with_correct_prompt(self, MockAgent):
        mock_instance = MagicMock()
        mock_instance.return_value = "Root cause: BMC unreachable. Recommend checking network."
        MockAgent.return_value = mock_instance

        result = handle_provisioning_failure(
            name="test-req",
            namespace="default",
            spec={"nodes": [{"hostname": "worker-003"}]},
            phase="Validating",
            error="BMC at 10.0.1.5 is not reachable",
        )

        assert "BMC unreachable" in result
        MockAgent.assert_called_once()
        prompt_arg = mock_instance.call_args[0][0]
        assert "worker-003" in prompt_arg
        assert "Validating" in prompt_arg
        assert "BMC at 10.0.1.5" in prompt_arg

    @patch("amzn_cse_telco_autonomous_network_agents_app.agent.agents.anpa.failure_handler.Agent")
    def test_handles_agent_crash_gracefully(self, MockAgent):
        MockAgent.side_effect = RuntimeError("Bedrock throttled")

        result = handle_provisioning_failure(
            name="test-req",
            namespace="default",
            spec={"hostname": "worker-001"},
            phase="Provisioning",
            error="Tinkerbell workflow failed",
        )

        assert "AI diagnosis failed" in result
        assert "Tinkerbell workflow failed" in result

    @patch("amzn_cse_telco_autonomous_network_agents_app.agent.agents.anpa.failure_handler.Agent")
    def test_multi_node_spec(self, MockAgent):
        mock_instance = MagicMock()
        mock_instance.return_value = "Checked both nodes"
        MockAgent.return_value = mock_instance

        handle_provisioning_failure(
            name="multi-req",
            namespace="tink",
            spec={"nodes": [{"hostname": "w1"}, {"hostname": "w2"}]},
            phase="WaitingForNodes",
            error="Timeout",
        )

        prompt_arg = mock_instance.call_args[0][0]
        assert "w1" in prompt_arg
        assert "w2" in prompt_arg

    @patch("amzn_cse_telco_autonomous_network_agents_app.agent.agents.anpa.failure_handler.Agent")
    def test_single_hostname_fallback(self, MockAgent):
        mock_instance = MagicMock()
        mock_instance.return_value = "Diagnosed single node"
        MockAgent.return_value = mock_instance

        handle_provisioning_failure(
            name="single-req",
            namespace="default",
            spec={"hostname": "edge-server-01"},
            phase="Pending",
            error="HardwareInventory CR not found",
        )

        prompt_arg = mock_instance.call_args[0][0]
        assert "edge-server-01" in prompt_arg


# ============================================================================
# Phase 4 — diagnosis persistence + tool-set enrichment
# ============================================================================


class TestDiagnosisPersistence:
    """P4.3 — failure handler stores its diagnosis for the API to read back."""

    def test_persists_ai_diagnosis(self, tmp_path, monkeypatch):
        monkeypatch.setenv("ANPA_DIAGNOSIS_DIR", str(tmp_path))
        import importlib
        import amzn_cse_telco_autonomous_network_agents_app.agent.agents.anpa.failure_handler as fh
        importlib.reload(fh)

        with patch.object(fh, "Agent") as MockAgent:
            mock_instance = MagicMock()
            mock_instance.return_value = (
                "ROOT CAUSE: stream-image checksum mismatch. "
                "EVIDENCE: get_workflow_logs returned STATE_FAILED. "
                "RECOMMENDATION: bump_provision_hash."
            )
            MockAgent.return_value = mock_instance

            diagnosis = fh.handle_provisioning_failure(
                name="rq-1",
                namespace="anpa-system",
                spec={"hostname": "server-1"},
                phase="Provisioning",
                error="Tinkerbell workflow STATE_FAILED",
            )

        assert "stream-image" in diagnosis
        record = fh.get_last_diagnosis("anpa-system", "rq-1")
        assert record is not None
        assert record["source"] == "ai"
        assert record["phase"] == "Provisioning"
        assert record["hostnames"] == ["server-1"]
        assert "stream-image" in record["diagnosis"]

    def test_persists_fallback_when_agent_crashes(self, tmp_path, monkeypatch):
        monkeypatch.setenv("ANPA_DIAGNOSIS_DIR", str(tmp_path))
        import importlib
        import amzn_cse_telco_autonomous_network_agents_app.agent.agents.anpa.failure_handler as fh
        importlib.reload(fh)

        with patch.object(fh, "Agent", side_effect=RuntimeError("Bedrock throttled")):
            fh.handle_provisioning_failure(
                name="rq-2",
                namespace="anpa-system",
                spec={"hostname": "x"},
                phase="WaitingForNodes",
                error="node never registered",
            )
        record = fh.get_last_diagnosis("anpa-system", "rq-2")
        assert record["source"] == "fallback"
        assert "Bedrock throttled" in record["exception"]

    def test_get_last_diagnosis_returns_none_when_absent(self, tmp_path, monkeypatch):
        monkeypatch.setenv("ANPA_DIAGNOSIS_DIR", str(tmp_path))
        import importlib
        import amzn_cse_telco_autonomous_network_agents_app.agent.agents.anpa.failure_handler as fh
        importlib.reload(fh)
        assert fh.get_last_diagnosis("ns", "missing") is None


class TestToolSetEnrichment:
    """P4.1 — DIAGNOSIS_TOOLS must be wired into the agent's tool list."""

    def test_diagnosis_tools_passed_to_agent(self, tmp_path, monkeypatch):
        monkeypatch.setenv("ANPA_DIAGNOSIS_DIR", str(tmp_path))
        import importlib
        import amzn_cse_telco_autonomous_network_agents_app.agent.agents.anpa.failure_handler as fh
        importlib.reload(fh)

        with patch.object(fh, "Agent") as MockAgent:
            mock_instance = MagicMock()
            mock_instance.return_value = "ok"
            MockAgent.return_value = mock_instance
            fh.handle_provisioning_failure("r", "ns", {"hostname": "h"}, "Provisioning", "err")
            args, kwargs = MockAgent.call_args[0], MockAgent.call_args[1]

        tools_passed = kwargs.get("tools") or (args[1] if len(args) > 1 else [])
        tool_names = {getattr(t, "__name__", "") for t in tools_passed}
        assert "get_workflow_logs" in tool_names
        assert "read_bmc_sel" in tool_names
        assert "inspect_node_join" in tool_names
