# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Tests for execution_logger and new evaluators."""
import json
import os
import tempfile
import pytest
from pathlib import Path
from unittest.mock import MagicMock

import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "webui" / "backend"))
sys.path.insert(0, str(Path(__file__).parent.parent / "evals"))


@pytest.fixture
def log_dir():
    d = tempfile.mkdtemp()
    os.environ["SOP_REPO"] = d
    yield Path(d) / "logs"


# ── ExecutionLogger tests ──

def test_execution_logger_full_lifecycle(log_dir):
    from execution_logger import ExecutionLogger

    log = ExecutionLogger(["/app/sops/01-argocd-setup.md"], eval_mode=True)
    log.node_start("01-argocd-setup")
    log.tool_call("01-argocd-setup", "kubectl", "get pods -n argocd")
    log.tool_result("01-argocd-setup", "tu-1", "NAME  READY  STATUS\nargocd-server  1/1  Running", False)
    log.node_complete("01-argocd-setup", "completed", 5000,
                      {"inputTokens": 100, "outputTokens": 200, "totalTokens": 300})
    log.node_start("eval-01-argocd-setup")
    log.eval_score("eval-01-argocd-setup", "SteeringEffectivenessEvaluator", 1.0, True, "No issues.")
    log.eval_score("eval-01-argocd-setup", "SOPCompletionEvaluator", 0.7, True, "Missing tools: [ssh_command]")
    log.node_complete("eval-01-argocd-setup", "completed", 200)
    log.graph_handoff(["eval-01-argocd-setup"], ["02-network-infra"])
    log.complete("completed", {"01-argocd-setup": "completed", "eval-01-argocd-setup": "completed"})

    files = list(log_dir.glob("execution_*.json"))
    assert len(files) == 1
    data = json.loads(files[0].read_text())
    assert data["status"] == "completed"
    assert data["summary"]["total_tool_calls"] == 1
    assert data["summary"]["total_tokens"] == 300
    assert len(data["nodes"]["01-argocd-setup"]["tool_calls"]) == 1
    assert data["nodes"]["01-argocd-setup"]["tool_calls"][0]["tool"] == "kubectl"
    assert data["nodes"]["01-argocd-setup"]["tool_calls"][0]["result"] is not None
    assert len(data["nodes"]["eval-01-argocd-setup"]["eval_scores"]) == 2
    assert len(data["graph_flow"]) == 1
    assert data["graph_flow"][0]["type"] == "handoff"


def test_execution_logger_error_handling(log_dir):
    from execution_logger import ExecutionLogger

    log = ExecutionLogger(["/app/sops/01.md"])
    log.node_start("01")
    log.add_error("RuntimeError: model unavailable", "01")
    log.complete("error")

    files = list(log_dir.glob("execution_*.json"))
    assert len(files) == 1
    data = json.loads(files[0].read_text())
    assert data["status"] == "error"
    assert len(data["errors"]) == 1
    assert data["nodes"]["01"]["error"] == "RuntimeError: model unavailable"


def test_execution_logger_and_join_tracking(log_dir):
    from execution_logger import ExecutionLogger

    log = ExecutionLogger(["/app/sops/07.md"])
    log.and_join_check("07-load-test", ["eval-01", "eval-02", "eval-04"], ["eval-01"], False)
    log.and_join_check("07-load-test", ["eval-01", "eval-02", "eval-04"], ["eval-01", "eval-02", "eval-04"], True)
    log.complete("completed")

    data = json.loads(list(log_dir.glob("execution_*.json"))[0].read_text())
    flow = [f for f in data["graph_flow"] if f["type"] == "and_join"]
    assert len(flow) == 2
    assert flow[0]["result"] is False
    assert flow[1]["result"] is True


def test_corrector_snapshot(log_dir):
    from execution_logger import ExecutionLogger

    log = ExecutionLogger(["/app/sops/02.md"])
    log.node_start("correct-02")
    log.corrector_snapshot("correct-02", "/app/sops/02.md", "# Original SOP\n\nContent here",
                           [{"reason": "Tool budget exceeded: 134/95"}])
    log.complete("completed")

    data = json.loads(list(log_dir.glob("execution_*.json"))[0].read_text())
    audit = data["nodes"]["correct-02"]["corrector_audit"]
    assert audit["original_lines"] == 3
    assert "Tool budget exceeded" in audit["failures_addressed"][0]


def test_list_and_get_executions(log_dir):
    from execution_logger import ExecutionLogger, list_executions, get_execution

    log = ExecutionLogger(["/app/sops/01.md"])
    log.complete("completed")

    records = list_executions()
    assert len(records) == 1
    assert records[0]["status"] == "completed"

    full = get_execution(log.run_id)
    assert full is not None
    assert full["run_id"] == log.run_id


def test_eval_history(log_dir):
    from execution_logger import ExecutionLogger, get_eval_history

    for i, score in enumerate([0.5, 0.8, 1.0]):
        log = ExecutionLogger(["/app/sops/01.md"], eval_mode=True)
        # Force unique run_id
        log.run_id = f"20260403_16503{i}"
        log.record["run_id"] = log.run_id
        log.node_start("eval-01-argocd-setup")
        log.eval_score("eval-01-argocd-setup", "Steering", score, score >= 0.5, f"Score: {score}")
        log.node_complete("eval-01-argocd-setup", "completed", 100)
        log.complete("completed")

    history = get_eval_history("01-argocd-setup")
    assert len(history) == 3


# ── New Evaluator tests ──

from evaluators import ExecutionTimeEvaluator, ToolSuccessRateEvaluator


class FakeCase:
    def __init__(self, metadata=None, trajectory=None, output=""):
        self.metadata = metadata or {}
        self.actual_trajectory = trajectory
        self.actual_output = output


def test_execution_time_within_budget():
    e = ExecutionTimeEvaluator()
    case = FakeCase(metadata={"bash_blocks": 10, "lines": 100, "execution_time_s": 60})
    results = e.evaluate(case)
    assert results[0].score == 1.0
    assert results[0].test_pass is True


def test_execution_time_slow():
    e = ExecutionTimeEvaluator()
    # Budget = max(120, 60 + 10*5 + 100//2) = max(120, 160) = 160s
    case = FakeCase(metadata={"bash_blocks": 10, "lines": 100, "execution_time_s": 200})
    results = e.evaluate(case)
    assert results[0].score == 0.7


def test_execution_time_timeout():
    e = ExecutionTimeEvaluator()
    case = FakeCase(metadata={"bash_blocks": 5, "lines": 50, "execution_time_s": 600})
    results = e.evaluate(case)
    assert results[0].score == 0.0


def test_execution_time_no_data():
    e = ExecutionTimeEvaluator()
    case = FakeCase(metadata={})
    results = e.evaluate(case)
    assert results[0].test_pass is True


def test_tool_success_rate_no_spans():
    e = ToolSuccessRateEvaluator()
    case = FakeCase()
    results = e.evaluate(case)
    assert results[0].test_pass is True


def _make_tool_spans(total, failed_count, error_msg="connection refused"):
    """Create mock tool spans for evaluator testing."""
    from strands_evals.types.trace import Session

    spans = []
    for i in range(total):
        span = MagicMock()
        span.tool_call = MagicMock()
        span.tool_call.name = "kubectl"
        span.tool_result = MagicMock()
        span.tool_result.error = error_msg if i < failed_count else None
        # Make isinstance check work
        from strands_evals.types.trace import ToolExecutionSpan
        span.__class__ = ToolExecutionSpan
        spans.append(span)

    trace = MagicMock()
    trace.spans = spans
    session = MagicMock(spec=Session)
    session.traces = [trace]
    return session


def test_tool_success_rate_all_pass():
    e = ToolSuccessRateEvaluator()
    session = _make_tool_spans(10, 0)
    case = FakeCase(trajectory=session)
    results = e.evaluate(case)
    assert results[0].score == 1.0


def test_tool_success_rate_high_failure():
    e = ToolSuccessRateEvaluator()
    session = _make_tool_spans(10, 8, "connection refused")
    case = FakeCase(trajectory=session)
    results = e.evaluate(case)
    assert results[0].score == 0.0
    assert "connection refused" in results[0].reason


def test_tool_success_rate_moderate_failure():
    e = ToolSuccessRateEvaluator()
    session = _make_tool_spans(10, 3, "timeout")
    case = FakeCase(trajectory=session)
    results = e.evaluate(case)
    assert results[0].score == 0.7  # 70% success
