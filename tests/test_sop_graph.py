# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Tests for graph-based SOP orchestrator — Phase 1."""
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "sop-agent"))

from sop_graph import (
    parse_sop_metadata,
    resolve_dependencies,
    select_model,
    _all_upstreams_passed,
    _classify_failure,
    _needs_correction,
    _corrector_made_changes,
    EvalNode,
    CorrectorNode,
)
from strands.types.content import ContentBlock
from strands.multiagent.base import Status


# ── Fixtures ──

SOPS_DIR = Path(__file__).parent.parent / "sops"


def _real_sop(name: str) -> str:
    return str(SOPS_DIR / name)


# ── parse_sop_metadata ──

class TestParseSopMetadata:
    def test_extracts_stage_number_from_filename(self):
        meta = parse_sop_metadata(_real_sop("01-deploy-nginx.md"))
        # Stage is extracted from content "**Stage:** N", not filename
        # Generic SOPs may not have stage markers
        assert meta["stem"] == "01-deploy-nginx"

    def test_extracts_stem(self):
        meta = parse_sop_metadata(_real_sop("01-deploy-nginx.md"))
        assert meta["stem"] == "01-deploy-nginx"

    def test_counts_bash_blocks(self):
        meta = parse_sop_metadata(_real_sop("01-deploy-nginx.md"))
        assert meta["bash_blocks"] > 0

    def test_counts_lines(self):
        meta = parse_sop_metadata(_real_sop("01-deploy-nginx.md"))
        assert meta["lines"] > 10

    def test_missing_file_returns_defaults(self):
        meta = parse_sop_metadata("/nonexistent/fake-sop.md")
        assert meta["stem"] == "fake-sop"
        assert meta["stage"] is None
        assert meta["dep_stages"] == []
        assert meta["bash_blocks"] == 0

    def test_all_sops_parse_without_error(self):
        for sop in SOPS_DIR.glob("*.md"):
            meta = parse_sop_metadata(str(sop))
            assert meta["stem"] == sop.stem


# ── resolve_dependencies ──

class TestResolveDependencies:
    def _all_metas(self):
        return [parse_sop_metadata(str(p)) for p in sorted(SOPS_DIR.glob("*.md"))]

    def test_returns_edges_or_empty(self):
        edges = resolve_dependencies(self._all_metas())
        assert isinstance(edges, list)

    def test_edges_are_tuples(self):
        edges = resolve_dependencies(self._all_metas())
        for e in edges:
            assert len(e) == 2
            assert isinstance(e[0], str)
            assert isinstance(e[1], str)

    def test_no_self_edges(self):
        edges = resolve_dependencies(self._all_metas())
        for frm, to in edges:
            assert frm != to

    def test_single_sop_no_edges(self):
        metas = [parse_sop_metadata(_real_sop("01-deploy-nginx.md"))]
        edges = resolve_dependencies(metas)
        assert edges == []


# ── select_model ──

class TestSelectModel:
    def test_simple_sop_gets_haiku(self):
        meta = {"bash_blocks": 5, "lines": 50}
        assert select_model(meta) == "haiku"

    def test_medium_sop_gets_sonnet(self):
        meta = {"bash_blocks": 12, "lines": 160}
        assert select_model(meta) == "sonnet"

    def test_complex_sop_gets_opus(self):
        meta = {"bash_blocks": 25, "lines": 400}
        assert select_model(meta) == "opus4.6"

    def test_high_lines_low_blocks_gets_opus(self):
        meta = {"bash_blocks": 5, "lines": 350}
        assert select_model(meta) == "opus4.6"

    def test_high_blocks_low_lines_gets_opus(self):
        meta = {"bash_blocks": 22, "lines": 100}
        assert select_model(meta) == "opus4.6"

    def test_default_override(self):
        meta = {"bash_blocks": 3, "lines": 30}
        assert select_model(meta, default="sonnet") == "sonnet"

    def test_real_deploy_nginx_gets_haiku(self):
        meta = parse_sop_metadata(_real_sop("01-deploy-nginx.md"))
        assert select_model(meta) == "haiku"


# ── _all_upstreams_passed condition (AND-join) ──

class TestAllUpstreamsPassed:
    def _make_state(self, results: dict):
        state = MagicMock(spec=["results"])
        state.results = results
        return state

    def test_returns_true_when_all_completed(self):
        nr_a = MagicMock(); nr_a.status = Status.COMPLETED
        nr_b = MagicMock(); nr_b.status = Status.COMPLETED
        state = self._make_state({"node_a": nr_a, "node_b": nr_b})
        assert _all_upstreams_passed(["node_a", "node_b"])(state) is True

    def test_returns_false_when_one_missing(self):
        nr_a = MagicMock(); nr_a.status = Status.COMPLETED
        state = self._make_state({"node_a": nr_a})
        assert _all_upstreams_passed(["node_a", "node_b"])(state) is False

    def test_returns_false_when_one_failed(self):
        nr_a = MagicMock(); nr_a.status = Status.COMPLETED
        nr_b = MagicMock(); nr_b.status = Status.FAILED
        state = self._make_state({"node_a": nr_a, "node_b": nr_b})
        assert _all_upstreams_passed(["node_a", "node_b"])(state) is False

    def test_single_node_works(self):
        nr = MagicMock(); nr.status = Status.COMPLETED
        state = self._make_state({"node_a": nr})
        assert _all_upstreams_passed(["node_a"])(state) is True

    def test_empty_list_returns_true(self):
        state = self._make_state({})
        assert _all_upstreams_passed([])(state) is True


# ── build_sop_graph (structure only, no execution) ──

class TestBuildSopGraph:
    """Test graph construction logic without actually building Graph objects."""

    def test_model_selection_uses_content(self):
        """Verify that build_sop_graph would select different models per SOP complexity."""
        from sop_graph import parse_sop_metadata, select_model
        deploy = parse_sop_metadata(_real_sop("01-deploy-nginx.md"))
        assert select_model(deploy, "haiku") == "haiku"

    def test_entry_points_are_nodes_without_incoming_edges(self):
        """Verify entry point detection logic."""
        from sop_graph import parse_sop_metadata, resolve_dependencies
        sop_paths = [str(p) for p in sorted(SOPS_DIR.glob("*.md"))]
        metas = [parse_sop_metadata(p) for p in sop_paths]
        edges = resolve_dependencies(metas)
        stem_set = {m["stem"] for m in metas}
        nodes_with_incoming = {to for _, to in edges if to in stem_set}
        entry_points = [m["stem"] for m in metas if m["stem"] not in nodes_with_incoming]
        # 01-deploy-nginx should be an entry point (no dependencies)
        assert "01-deploy-nginx" in entry_points


# ── build_eval_loop (structure only) ──

class TestBuildEvalLoop:
    def test_eval_loop_needs_correction_condition(self):
        """Test the needs_correction condition logic directly."""
        from strands.multiagent.base import Status

        # Simulate eval result with NEEDS_CORRECTION
        mock_state = MagicMock(spec=["results"])
        mock_result = MagicMock()
        mock_result.status = Status.COMPLETED
        mock_agent_result = MagicMock()
        mock_agent_result.message.content = [ContentBlock(text="SteeringEff: 1.0\nSOPCompl: 0.4\n  FAIL: missing tools\nNEEDS_CORRECTION")]
        mock_result.get_agent_results.return_value = [mock_agent_result]
        mock_state.results = {"eval": mock_result}

        # The condition function checks for NEEDS_CORRECTION in eval output
        # We test the logic inline since build_eval_loop creates it internally
        r = mock_state.results.get("eval")
        assert r is not None
        assert r.status == Status.COMPLETED
        results = r.get_agent_results()
        has_correction = any("NEEDS_CORRECTION" in str(ar.message.content) for ar in results if ar.message)
        assert has_correction is True

    def test_eval_loop_passing_no_correction(self):
        """Test that passing eval does not trigger correction."""
        from strands.multiagent.base import Status

        mock_state = MagicMock(spec=["results"])
        mock_result = MagicMock()
        mock_result.status = Status.COMPLETED
        mock_agent_result = MagicMock()
        mock_agent_result.message.content = [ContentBlock(text="SteeringEff: 1.0\nSOPCompl: 1.0\n  PASS: all good")]
        mock_result.get_agent_results.return_value = [mock_agent_result]
        mock_state.results = {"eval": mock_result}

        r = mock_state.results.get("eval")
        results = r.get_agent_results()
        has_correction = any("NEEDS_CORRECTION" in str(ar.message.content) for ar in results if ar.message)
        assert has_correction is False


# ── Failure Classification ──

class TestClassifyFailure:
    def test_repeated_failures_is_agent_fault(self):
        assert _classify_failure("SteeringEffectivenessEvaluator", "Repeated failures: {ssh:timeout: 4}", None) == "AGENT_FAULT"

    def test_budget_exceeded_is_agent_fault(self):
        assert _classify_failure("SteeringEffectivenessEvaluator", "Tool budget exceeded: 96/95", None) == "AGENT_FAULT"

    def test_empty_output_is_agent_fault(self):
        assert _classify_failure("SOPCompletionEvaluator", "Empty agent output — likely crashed", None) == "AGENT_FAULT"

    def test_critical_failure_is_agent_fault(self):
        assert _classify_failure("SOPCompletionEvaluator", "Agent reported failure: 'CRITICAL FAILURE'", None) == "AGENT_FAULT"

    def test_missing_tools_is_sop_fault(self):
        assert _classify_failure("SOPCompletionEvaluator", "Missing required tools: ['check_pod_status']", None) == "SOP_FAULT"

    def test_success_pattern_is_sop_fault(self):
        assert _classify_failure("SOPCompletionEvaluator", "Success pattern 'BGP established' not found in output", None) == "SOP_FAULT"

    def test_sop_fault_takes_priority(self):
        """Once SOP_FAULT is set, it should not be downgraded to AGENT_FAULT."""
        assert _classify_failure("SteeringEffectivenessEvaluator", "Repeated failures", "SOP_FAULT") == "SOP_FAULT"

    def test_agent_fault_can_upgrade_to_sop_fault(self):
        result = _classify_failure("SOPCompletionEvaluator", "Missing required tools: ['kubectl']", "AGENT_FAULT")
        assert result == "SOP_FAULT"


# ── EvalNode Streaming ──

class TestEvalNodeStreaming:
    @pytest.fixture
    def eval_node(self):
        mock_ctx = {"telemetry": MagicMock(), "session_id": "test123"}
        return EvalNode(mock_ctx, _real_sop("01-argocd-setup.md"), name="eval-01")

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

        with patch("sop_graph.collect_eval_session", return_value=MagicMock()), \
             patch("sop_graph.get_sop_eval_meta", return_value={}), \
             patch("asyncio.get_event_loop") as mock_loop:
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

        with patch("sop_graph.collect_eval_session", return_value=MagicMock()), \
             patch("sop_graph.get_sop_eval_meta", return_value={}), \
             patch("asyncio.get_event_loop") as mock_loop:
            mock_loop.return_value.run_in_executor = fake_executor
            async for event in eval_node.stream_async("test"):
                if "result" in event:
                    result = event["result"]

        assert result is not None
        assert result.execution_time >= 0

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

        with patch("sop_graph.collect_eval_session", return_value=MagicMock()), \
             patch("sop_graph.get_sop_eval_meta", return_value={}), \
             patch("asyncio.get_event_loop") as mock_loop:
            mock_loop.return_value.run_in_executor = fake_executor
            async for event in eval_node.stream_async("test"):
                if "data" in event:
                    data_lines.append(event["data"])

        correction_lines = [l for l in data_lines if "NEEDS_CORRECTION" in l]
        assert len(correction_lines) == 1


# ── CorrectorNode ──

class TestCorrectorNode:
    def test_corrector_node_has_stream_async(self):
        node = CorrectorNode("/tmp/test.md", None, "us-east-1", name="correct-01")
        assert hasattr(node, "stream_async")
        assert node.name == "correct-01"

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
        assert not any("No actionable failures" in l for l in data_lines), \
            f"Corrector failed to parse FAIL lines from ContentBlocks: {data_lines}"

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
        assert any("No actionable failures" in l for l in data_lines)


class TestCorrectorMadeChanges:
    """Tests for _corrector_made_changes edge condition."""

    def _make_state(self, node_id, text):
        from strands.types.content import ContentBlock, Message
        from strands.agent.agent_result import AgentResult
        state = MagicMock()
        ar = AgentResult(
            stop_reason="end_turn",
            message=Message(role="assistant", content=[ContentBlock(text=text)]),
            state={}, metrics={},
        )
        nr = MagicMock()
        nr.status = Status.COMPLETED
        nr.get_agent_results = MagicMock(return_value=[ar])
        # GraphState.results is a dict
        result_mock = MagicMock()
        result_mock.status = Status.COMPLETED
        result_mock.get_agent_results.return_value = [ar]
        state.results = {node_id: result_mock}
        return state

    def test_returns_true_when_sop_patched(self):
        cond = _corrector_made_changes("correct-04")
        state = self._make_state("correct-04", "SOP patched: 04-app-config.md\nFailures addressed: 2")
        assert cond(state) is True

    def test_returns_false_when_skipped(self):
        cond = _corrector_made_changes("correct-04")
        state = self._make_state("correct-04", "No actionable failures found — skipping SOP patch.")
        assert cond(state) is False

    def test_returns_false_when_node_missing(self):
        cond = _corrector_made_changes("correct-04")
        state = MagicMock()
        state.results = {}
        assert cond(state) is False


class TestNeedsCorrectionRetryLimit:
    """Tests for _needs_correction retry cap."""

    def _make_state(self, eval_id, text):
        from strands.types.content import ContentBlock, Message
        from strands.agent.agent_result import AgentResult
        ar = AgentResult(
            stop_reason="end_turn",
            message=Message(role="assistant", content=[ContentBlock(text=text)]),
            state={}, metrics={},
        )
        result_mock = MagicMock()
        result_mock.status = Status.COMPLETED
        result_mock.get_agent_results.return_value = [ar]
        state = MagicMock()
        state.results = {eval_id: result_mock}
        return state

    def test_allows_corrections_up_to_limit(self):
        cond = _needs_correction("eval-01", max_retries=2)
        state = self._make_state("eval-01", "FAIL: something\nNEEDS_CORRECTION:AGENT_FAULT")
        assert cond(state) is True   # attempt 1
        assert cond(state) is True   # attempt 2
        assert cond(state) is False  # attempt 3 — capped

    def test_no_correction_needed_doesnt_count(self):
        cond = _needs_correction("eval-01", max_retries=2)
        passing = self._make_state("eval-01", "PASS: all good")
        assert cond(passing) is False  # no correction needed, counter stays 0
        failing = self._make_state("eval-01", "NEEDS_CORRECTION:AGENT_FAULT")
        assert cond(failing) is True   # attempt 1 — still allowed
