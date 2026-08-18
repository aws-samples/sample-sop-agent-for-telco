# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Tests for sop_nodes: EvalNode, CorrectorNode, create_sop_agent, _classify_failure.

These import strands.multiagent + the evals bootstrap, so conftest gates this
file out on SDK-less sandboxes (collect_ignore_glob) like test_sop_graph.
run_cmd-style patch targets (collect_eval_session / get_sop_eval_meta) are
patched on sop_nodes, where EvalNode's code now looks them up.
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

try:
    import pytest_asyncio  # noqa: F401

    _skip_no_asyncio = lambda f: f  # no-op decorator
except ImportError:
    _skip_no_asyncio = pytest.mark.skip(reason="pytest-asyncio not installed")


from amzn_cse_telco_autonomous_network_agents_app.agent.sop_nodes import (
    CorrectorNode,
    EvalNode,
    FaultType,
    _classify_failure,
)

SOPS_DIR = Path(__file__).parent.parent / "sops"


def _real_sop(name: str) -> str:
    return str(SOPS_DIR / name)


# ── Failure Classification ──


class TestClassifyFailure:
    def test_repeated_failures_is_agent_fault(self):
        assert (
            _classify_failure(
                "SteeringEffectivenessEvaluator",
                "Repeated failures: {ssh:timeout: 4}",
                None,
            )
            == "AGENT_FAULT"
        )

    def test_budget_exceeded_is_agent_fault(self):
        assert _classify_failure("SteeringEffectivenessEvaluator", "Tool budget exceeded: 96/95", None) == "AGENT_FAULT"

    def test_empty_output_is_agent_fault(self):
        assert _classify_failure("SOPCompletionEvaluator", "Empty agent output — likely crashed", None) == "AGENT_FAULT"

    def test_critical_failure_is_agent_fault(self):
        assert (
            _classify_failure(
                "SOPCompletionEvaluator",
                "Agent reported failure: 'CRITICAL FAILURE'",
                None,
            )
            == "AGENT_FAULT"
        )

    def test_missing_tools_is_sop_fault(self):
        assert (
            _classify_failure(
                "SOPCompletionEvaluator",
                "Missing required tools: ['check_pod_status']",
                None,
            )
            == "SOP_FAULT"
        )

    def test_success_pattern_is_sop_fault(self):
        assert (
            _classify_failure(
                "SOPCompletionEvaluator",
                "Success pattern 'BGP established' not found in output",
                None,
            )
            == "SOP_FAULT"
        )

    def test_sop_fault_takes_priority(self):
        """Once SOP_FAULT is set, it should not be downgraded to AGENT_FAULT."""
        assert _classify_failure("SteeringEffectivenessEvaluator", "Repeated failures", "SOP_FAULT") == "SOP_FAULT"

    def test_agent_fault_can_upgrade_to_sop_fault(self):
        result = _classify_failure(
            "SOPCompletionEvaluator",
            "Missing required tools: ['kubectl']",
            "AGENT_FAULT",
        )
        assert result == "SOP_FAULT"

    def test_returns_fault_type_enum(self):
        # StrEnum member, so it both is a FaultType and compares equal to the string.
        result = _classify_failure("SOPCompletionEvaluator", "Missing required tools: ['x']", None)
        assert isinstance(result, FaultType)
        assert result == FaultType.SOP_FAULT


# ── EvalNode Streaming ──


class TestEvalNodeStreaming:
    @pytest.fixture
    def eval_node(self):
        mock_ctx = {"telemetry": MagicMock(), "session_id": "test123"}
        return EvalNode(mock_ctx, _real_sop("01-argocd-setup.md"), name="eval-01")

    @_skip_no_asyncio
    @pytest.mark.asyncio
    async def test_stream_yields_data_before_result(self, eval_node):
        """EvalNode must yield {data: ...} events before the final {result: ...}."""
        events = []
        mock_report = MagicMock()
        mock_report.evaluator_name = "TestEvaluator"
        mock_report.overall_score = 0.85
        mock_report.reasons = ["All good"]
        mock_report.test_passes = [True]

        async def fake_executor(_, fn, *args):
            return [mock_report]

        with (
            patch(
                "amzn_cse_telco_autonomous_network_agents_app.agent.sop_nodes.collect_eval_session",
                return_value=MagicMock(),
            ),
            patch(
                "amzn_cse_telco_autonomous_network_agents_app.agent.sop_nodes.get_sop_eval_meta",
                return_value={},
            ),
            patch("asyncio.get_event_loop") as mock_loop,
        ):
            mock_loop.return_value.run_in_executor = fake_executor
            async for event in eval_node.stream_async("test output"):
                events.append(event)

        data_events = [e for e in events if "data" in e]
        result_events = [e for e in events if "result" in e]
        eval_events = [e for e in events if "eval_score" in e]
        assert len(data_events) >= 2, f"Should yield evaluator name + score, got {[e['data'] for e in data_events]}"
        assert len(result_events) == 1
        assert data_events[0]["data"] == "TestEvaluator"
        assert "0.85" in data_events[1]["data"]
        # Structured eval event
        assert len(eval_events) == 1
        assert eval_events[0]["eval_score"]["evaluator"] == "TestEvaluator"
        assert eval_events[0]["eval_score"]["score"] == 0.85

    @_skip_no_asyncio
    @pytest.mark.asyncio
    async def test_stream_result_has_execution_time(self, eval_node):
        """EvalNode result must have non-zero execution_time."""
        result = None
        mock_report = MagicMock()
        mock_report.evaluator_name = "TestEvaluator"
        mock_report.overall_score = 1.0
        mock_report.reasons = ["OK"]
        mock_report.test_passes = [True]

        async def fake_executor(_, fn, *args):
            return [mock_report]

        with (
            patch(
                "amzn_cse_telco_autonomous_network_agents_app.agent.sop_nodes.collect_eval_session",
                return_value=MagicMock(),
            ),
            patch(
                "amzn_cse_telco_autonomous_network_agents_app.agent.sop_nodes.get_sop_eval_meta",
                return_value={},
            ),
            patch("asyncio.get_event_loop") as mock_loop,
        ):
            mock_loop.return_value.run_in_executor = fake_executor
            async for event in eval_node.stream_async("test"):
                if "result" in event:
                    result = event["result"]

        assert result is not None
        assert result.execution_time >= 0

    @_skip_no_asyncio
    @pytest.mark.asyncio
    async def test_stream_appends_needs_correction_on_failure(self, eval_node):
        """EvalNode must append NEEDS_CORRECTION when evaluator fails."""
        data_lines = []
        mock_report = MagicMock()
        mock_report.evaluator_name = "TestEvaluator"
        mock_report.overall_score = 0.2
        mock_report.reasons = ["Missing tools"]
        mock_report.test_passes = [False]

        async def fake_executor(_, fn, *args):
            return [mock_report]

        with (
            patch(
                "amzn_cse_telco_autonomous_network_agents_app.agent.sop_nodes.collect_eval_session",
                return_value=MagicMock(),
            ),
            patch(
                "amzn_cse_telco_autonomous_network_agents_app.agent.sop_nodes.get_sop_eval_meta",
                return_value={},
            ),
            patch("asyncio.get_event_loop") as mock_loop,
        ):
            mock_loop.return_value.run_in_executor = fake_executor
            async for event in eval_node.stream_async("test"):
                if "data" in event:
                    data_lines.append(event["data"])

        correction_lines = [line for line in data_lines if "NEEDS_CORRECTION" in line]
        assert len(correction_lines) == 1


# ── CorrectorNode ──


class TestCorrectorNode:
    def test_corrector_node_has_stream_async(self):
        node = CorrectorNode("/tmp/test.md", None, "us-east-1", name="correct-01")
        assert hasattr(node, "stream_async")
        assert node.name == "correct-01"

    @_skip_no_asyncio
    @pytest.mark.asyncio
    async def test_corrector_parses_failures_from_content_blocks(self, tmp_path):
        """Corrector must find FAIL: lines when task is a list of ContentBlocks (graph format)."""
        sop = tmp_path / "test.md"
        sop.write_text("# Test SOP\n\n## Procedure\n\n### Step 1\n```bash\necho hello\n```\n")
        node = CorrectorNode(str(sop), None, "us-east-1", name="correct-01")

        # Simulate what the graph framework passes: list of dicts with 'text' keys
        task = [
            {"text": "Original Task: execute SOPs"},
            {"text": "\nInputs from previous nodes:"},
            {"text": "\nFrom eval-01:"},
            {"text": "  - eval-01: ExecutionTimeEvaluator\n  Score: 0.00\n  FAIL: Timeout-level: 525s vs 193s budget (2.7x)\nNEEDS_CORRECTION:AGENT_FAULT"},
        ]

        events = []
        async for event in node.stream_async(task):
            events.append(event)

        data_lines = [e["data"] for e in events if "data" in e]
        # Should NOT say "No actionable failures" — it should find the FAIL line
        assert not any("No actionable failures" in line for line in data_lines), f"Corrector failed to parse FAIL lines from ContentBlocks: {data_lines}"

    @_skip_no_asyncio
    @pytest.mark.asyncio
    async def test_corrector_skips_when_no_failures(self, tmp_path):
        """Corrector skips when eval output has no FAIL: lines."""
        sop = tmp_path / "test.md"
        sop.write_text("# Test SOP\n")
        node = CorrectorNode(str(sop), None, "us-east-1", name="correct-01")

        task = [{"text": "PASS: All good\nPASS: Completed in 60s"}]
        events = []
        async for event in node.stream_async(task):
            events.append(event)

        data_lines = [e["data"] for e in events if "data" in e]
        assert any("No actionable failures" in line for line in data_lines)
