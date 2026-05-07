# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""Tests for SOPSteeringHooks — steering hooks for SOP executor agent."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "sop-agent"))

from unittest.mock import MagicMock
from sop_executor import SOPSteeringHooks


def _make_event(name, inp=None, cancel_tool=False):
    """Create a mock BeforeToolCallEvent."""
    event = MagicMock()
    event.tool_use = {"name": name, "input": inp or {}, "toolUseId": "test-id"}
    event.cancel_tool = cancel_tool
    return event


def _make_after_event(name, result_text="ok"):
    """Create a mock AfterToolCallEvent."""
    event = MagicMock()
    event.tool_use = {"name": name, "input": {}, "toolUseId": "test-id"}
    event.result = {"content": [{"text": result_text}]}
    return event


class TestSSHHeredocGuard:
    def test_long_heredoc_blocked(self):
        hooks = SOPSteeringHooks()
        cmd = "cat << 'EOF'\n" + "x" * 600 + "\nEOF"
        event = _make_event("ssh_command", {"command": cmd, "host": "10.10.2.196"})
        hooks._before_tool_call(event)
        assert isinstance(event.cancel_tool, str)
        assert "base64" in event.cancel_tool

    def test_short_ssh_allowed(self):
        hooks = SOPSteeringHooks()
        event = _make_event("ssh_command", {"command": "ls -la", "host": "10.10.2.196"})
        hooks._before_tool_call(event)
        assert event.cancel_tool is False

    def test_local_heredoc_allowed(self):
        hooks = SOPSteeringHooks()
        cmd = "cat << 'EOF'\n" + "x" * 600 + "\nEOF"
        event = _make_event("run_command", {"command": cmd})
        hooks._before_tool_call(event)
        assert event.cancel_tool is False


class TestToolCallBudget:
    def test_stops_at_limit(self):
        hooks = SOPSteeringHooks()
        hooks.tool_count = 94  # next call will be 95
        event = _make_event("kubectl", {"args": "get pods -n aws-app"})
        hooks._before_tool_call(event)
        assert isinstance(event.cancel_tool, str)
        assert "budget" in event.cancel_tool.lower()

    def test_warns_near_limit(self):
        hooks = SOPSteeringHooks()
        hooks.tool_count = 79  # next call will be 80
        event = _make_event("kubectl", {"args": "get pods -n aws-app"})
        hooks._before_tool_call(event)
        # Should warn but NOT block
        assert event.cancel_tool is False


class TestNamespaceGuard:
    def test_default_namespace_blocked(self):
        hooks = SOPSteeringHooks()
        event = _make_event("kubectl", {"args": "get pods -n default"})
        hooks._before_tool_call(event)
        assert isinstance(event.cancel_tool, str)
        assert "aws-app" in event.cancel_tool

    def test_kubectl_exec_default_blocked(self):
        hooks = SOPSteeringHooks()
        event = _make_event("kubectl_exec", {"namespace": "default", "pod": "app-mgmt", "command": "ls"})
        hooks._before_tool_call(event)
        assert isinstance(event.cancel_tool, str)
        assert "aws-app" in event.cancel_tool

    def test_correct_namespace_allowed(self):
        hooks = SOPSteeringHooks()
        event = _make_event("kubectl", {"args": "get pods -n aws-app"})
        hooks._before_tool_call(event)
        assert event.cancel_tool is False

    def test_other_namespace_allowed(self):
        hooks = SOPSteeringHooks()
        event = _make_event("kubectl", {"args": "get pods -n monitoring"})
        hooks._before_tool_call(event)
        assert event.cancel_tool is False


class TestDangerousCommandGuard:
    def test_reboot_blocked_report_mode(self):
        hooks = SOPSteeringHooks(fix_mode=False)
        event = _make_event("ssh_command", {"command": "sudo reboot", "host": "10.10.2.196"})
        hooks._before_tool_call(event)
        assert isinstance(event.cancel_tool, str)
        assert "REPORT mode" in event.cancel_tool

    def test_reboot_allowed_fix_mode(self):
        hooks = SOPSteeringHooks(fix_mode=True)
        event = _make_event("ssh_command", {"command": "sudo reboot", "host": "10.10.2.196"})
        hooks._before_tool_call(event)
        assert event.cancel_tool is False

    def test_force_delete_blocked_report_mode(self):
        hooks = SOPSteeringHooks(fix_mode=False)
        event = _make_event("kubectl", {"args": "delete pod app-svc --force --grace-period=0"})
        hooks._before_tool_call(event)
        assert isinstance(event.cancel_tool, str)

    def test_pkill_blocked_report_mode(self):
        hooks = SOPSteeringHooks(fix_mode=False)
        event = _make_event("run_command", {"command": "pkill -9 trex"})
        hooks._before_tool_call(event)
        assert isinstance(event.cancel_tool, str)


class TestPortForwardGuard:
    def test_port_forward_no_background_blocked(self):
        hooks = SOPSteeringHooks()
        event = _make_event("run_command", {"command": "kubectl port-forward svc/prometheus 9090:9090"})
        hooks._before_tool_call(event)
        assert isinstance(event.cancel_tool, str)
        assert "background" in event.cancel_tool.lower() or "&" in event.cancel_tool

    def test_port_forward_with_background_allowed(self):
        hooks = SOPSteeringHooks()
        event = _make_event("run_command", {"command": "kubectl port-forward svc/prometheus 9090:9090 &"})
        hooks._before_tool_call(event)
        assert event.cancel_tool is False


class TestLedger:
    def test_after_tool_call_records(self):
        hooks = SOPSteeringHooks()
        event = _make_after_event("kubectl", "NAME  READY  STATUS\nupf-mgmt  1/1  Running")
        hooks._after_tool_call(event)
        assert len(hooks.ledger) == 1
        assert hooks.ledger[0]["tool"] == "kubectl"

    def test_ledger_accumulates(self):
        hooks = SOPSteeringHooks()
        hooks._after_tool_call(_make_after_event("kubectl", "ok"))
        hooks._after_tool_call(_make_after_event("ssh_command", "done"))
        assert len(hooks.ledger) == 2


# ============== Phase 1: Eval Telemetry Tests ==============
from sop_executor import setup_eval_telemetry, collect_eval_session


class TestEvalTelemetry:
    def test_setup_returns_telemetry_with_exporter(self):
        telemetry = setup_eval_telemetry()
        assert telemetry.in_memory_exporter is not None
        assert hasattr(telemetry.in_memory_exporter, "get_finished_spans")

    def test_collect_session_returns_session(self):
        telemetry = setup_eval_telemetry()
        # No spans yet — should still return a session object without error
        session = collect_eval_session(telemetry, "test-session-id")
        assert session is not None

    def test_exporter_clear_resets_spans(self):
        telemetry = setup_eval_telemetry()
        spans_before = telemetry.in_memory_exporter.get_finished_spans()
        telemetry.in_memory_exporter.clear()
        spans_after = telemetry.in_memory_exporter.get_finished_spans()
        assert len(spans_after) == 0


# ============== Phase 2: Evaluator Tests ==============
import sys as _sys
_sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "evals"))
from evaluators import SteeringEffectivenessEvaluator, SOPCompletionEvaluator
from strands_evals.types import EvaluationData
from strands_evals.types.trace import (
    Session, Trace, ToolExecutionSpan, ToolCall, ToolResult, SpanInfo,
)
from sop_executor import get_sop_eval_meta
from datetime import datetime, timezone


def _make_tool_span(name, error=None):
    now = datetime.now(timezone.utc)
    return ToolExecutionSpan(
        span_info=SpanInfo(session_id="test", start_time=now, end_time=now),
        tool_call=ToolCall(name=name, arguments={}),
        tool_result=ToolResult(content="ok", error=error),
    )


def _make_session(tool_spans):
    return Session(
        session_id="test",
        traces=[Trace(trace_id="t1", session_id="test", spans=tool_spans)],
    )


class TestSteeringEffectivenessEvaluator:
    def test_clean_run_scores_high(self):
        spans = [_make_tool_span("kubectl"), _make_tool_span("check_pod_status")]
        session = _make_session(spans)
        case = EvaluationData(input="test", actual_output="done", actual_trajectory=session)
        results = SteeringEffectivenessEvaluator().evaluate(case)
        assert results[0].score == 1.0

    def test_repeated_failures_scores_low(self):
        spans = [_make_tool_span("ssh_command", error="timeout")] * 4
        session = _make_session(spans)
        case = EvaluationData(input="test", actual_output="failed", actual_trajectory=session)
        results = SteeringEffectivenessEvaluator().evaluate(case)
        assert results[0].score < 1.0
        assert "Repeated failures" in results[0].reason

    def test_budget_exceeded_scores_zero(self):
        spans = [_make_tool_span("kubectl")] * 96
        session = _make_session(spans)
        case = EvaluationData(input="test", actual_output="died", actual_trajectory=session)
        results = SteeringEffectivenessEvaluator().evaluate(case)
        assert results[0].score == 0.0

    def test_no_spans_returns_no_data(self):
        case = EvaluationData(input="test", actual_output="ok", actual_trajectory=None)
        results = SteeringEffectivenessEvaluator().evaluate(case)
        assert results[0].label == "no_data"


class TestSOPCompletionEvaluator:
    def test_all_required_tools_called(self):
        spans = [_make_tool_span("check_pod_status"), _make_tool_span("kubectl_exec")]
        session = _make_session(spans)
        case = EvaluationData(
            input="test", actual_output="All checks passed",
            actual_trajectory=session,
            metadata={"required_tools": ["check_pod_status", "kubectl_exec"]},
        )
        results = SOPCompletionEvaluator().evaluate(case)
        assert results[0].score == 1.0

    def test_missing_required_tool(self):
        spans = [_make_tool_span("kubectl")]
        session = _make_session(spans)
        case = EvaluationData(
            input="test", actual_output="done",
            actual_trajectory=session,
            metadata={"required_tools": ["kubectl", "check_pod_status"]},
        )
        results = SOPCompletionEvaluator().evaluate(case)
        assert results[0].score < 1.0
        assert "Missing" in results[0].reason

    def test_kubectl_family_satisfies_kubectl(self):
        """kubectl_exec or check_pod_status should satisfy a 'kubectl' requirement."""
        spans = [_make_tool_span("kubectl_exec"), _make_tool_span("check_pod_status")]
        session = _make_session(spans)
        case = EvaluationData(
            input="test", actual_output="All checks passed",
            actual_trajectory=session,
            metadata={"required_tools": ["kubectl"]},
        )
        results = SOPCompletionEvaluator().evaluate(case)
        assert results[0].score == 1.0

    def test_empty_output_fails(self):
        case = EvaluationData(
            input="test", actual_output="",
            actual_trajectory=_make_session([]),
            metadata={},
        )
        results = SOPCompletionEvaluator().evaluate(case)
        assert "Empty" in results[0].reason


class TestSOPEvalMeta:
    def test_deploy_nginx_sop_meta(self):
        sop_path = os.path.join(os.path.dirname(__file__), "..", "sops", "01-deploy-nginx.md")
        meta = get_sop_eval_meta(sop_path)
        # Generic SOPs may not have required_tools defined
        assert isinstance(meta, dict)

    def test_unknown_sop_returns_empty(self):
        meta = get_sop_eval_meta("/tmp/nonexistent-sop-99.md")
        assert meta == {}


# ============== Phase 3: SOP Corrector Tests ==============
from sop_corrector import extract_failures, build_correction_prompt, correct_sop, MAX_CORRECTIONS_PER_SESSION
from strands_evals.types.evaluation_report import EvaluationReport


def _make_report(name, scores, passes, reasons):
    return EvaluationReport(
        evaluator_name=name,
        overall_score=sum(scores) / len(scores),
        scores=scores,
        cases=[],
        test_passes=passes,
        reasons=reasons,
        detailed_results=[],
    )


class TestExtractFailures:
    def test_extracts_failures_only(self):
        report = _make_report("TestEval", [1.0, 0.0], [True, False], ["ok", "missing tool"])
        failures = extract_failures([report])
        assert len(failures) == 1
        assert failures[0]["reason"] == "missing tool"
        assert failures[0]["evaluator"] == "TestEval"

    def test_no_failures_returns_empty(self):
        report = _make_report("TestEval", [1.0], [True], ["all good"])
        assert extract_failures([report]) == []


class TestBuildCorrectionPrompt:
    def test_includes_failures_and_sop(self):
        prompt = build_correction_prompt(
            "# My SOP\n## Step 1\nDo something",
            [{"evaluator": "E1", "reason": "missing pod check"}],
        )
        assert "missing pod check" in prompt
        assert "# My SOP" in prompt
        assert "E1" in prompt


class TestCorrectSopGuardrails:
    def test_no_failures_returns_none(self):
        report = _make_report("E", [1.0], [True], ["ok"])
        result = correct_sop([report], "/tmp/fake.md")
        assert result is None

    def test_max_corrections_enforced(self):
        report = _make_report("E", [0.0], [False], ["fail"])
        counter = {"fake": MAX_CORRECTIONS_PER_SESSION}
        result = correct_sop([report], "/tmp/fake.md", _correction_count=counter)
        assert result is None

    def test_failure_marker_in_output(self):
        spans = [_make_tool_span("kubectl"), _make_tool_span("check_pod_status")]
        session = _make_session(spans)
        case = EvaluationData(
            input="test",
            actual_output="❌ FAILURE: SOP 08-teardown.md CANNOT BE FULLY EXECUTED",
            actual_trajectory=session,
            metadata={"required_tools": ["kubectl", "check_pod_status"]},
        )
        results = SOPCompletionEvaluator().evaluate(case)
        assert results[0].score < 1.0
        assert "Agent reported failure" in results[0].reason
