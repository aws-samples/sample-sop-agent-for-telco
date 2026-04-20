# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Custom evaluators for SOP executor agent — deterministic, no LLM judge needed."""
from strands_evals.evaluators import Evaluator
from strands_evals.types import EvaluationData, EvaluationOutput
from strands_evals.types.trace import ToolExecutionSpan, Session


def _extract_tool_spans(trajectory) -> list[ToolExecutionSpan]:
    """Extract ToolExecutionSpan objects from a Session trajectory."""
    if not trajectory or not isinstance(trajectory, Session):
        return []
    spans = []
    for trace in trajectory.traces:
        for span in trace.spans:
            if isinstance(span, ToolExecutionSpan):
                spans.append(span)
    return spans


class SteeringEffectivenessEvaluator(Evaluator[str, str]):
    """Evaluates whether steering hooks prevented wasted tool calls.

    Checks:
    - Repeated failed tool calls (same tool, same error, 3+ times) = bad
    - Total tool calls vs budget (derived from SOP complexity)
    - Cancelled tool calls present = hooks working
    """

    BUDGET_WARN_BASE = 40
    BUDGET_FAIL_BASE = 50

    def evaluate(self, case: EvaluationData[str, str]) -> list[EvaluationOutput]:
        tool_spans = _extract_tool_spans(case.actual_trajectory)
        if not tool_spans:
            return [EvaluationOutput(
                score=0.5, test_pass=True,
                reason="No tool spans captured — cannot evaluate steering effectiveness.",
                label="no_data",
            )]

        total = len(tool_spans)
        issues = []

        # Derive budget from SOP complexity (bash_blocks, lines) if available
        meta = case.metadata or {}
        bash_blocks = meta.get("bash_blocks", 0)
        lines = meta.get("lines", 0)
        budget_fail = max(self.BUDGET_FAIL_BASE, bash_blocks * 8 + lines // 10)
        budget_warn = max(self.BUDGET_WARN_BASE, int(budget_fail * 0.8))

        # Check for repeated failures (same tool + error 3+ times)
        failure_counts: dict[str, int] = {}
        for span in tool_spans:
            if span.tool_result and span.tool_result.error:
                key = f"{span.tool_call.name}:{span.tool_result.error[:100]}"
                failure_counts[key] = failure_counts.get(key, 0) + 1
        repeated = {k: v for k, v in failure_counts.items() if v >= 3}
        if repeated:
            issues.append(f"Repeated failures: {repeated}")

        # Check tool budget
        if total >= budget_fail:
            issues.append(f"Tool budget exceeded: {total}/{budget_fail}")
        elif total >= budget_warn:
            issues.append(f"Tool budget warning: {total}/{budget_warn}")

        # Check if agent reported catastrophic failure despite low tool count
        output = str(case.actual_output or "")
        catastrophic = ["CRITICAL FAILURE", "CANNOT EXECUTE", "COMPLETELY FAILED", "Cannot fork"]
        if any(m in output for m in catastrophic):
            issues.append("Agent hit infrastructure failure")

        # Score
        if not issues:
            score = 1.0
        elif any("exceeded" in i for i in issues):
            score = 0.0
        elif repeated:
            score = max(0.0, 1.0 - 0.2 * len(repeated))
        else:
            score = 0.7  # warning-level

        return [EvaluationOutput(
            score=score,
            test_pass=score >= 0.5,
            reason=f"{total} tool calls. " + (" | ".join(issues) if issues else "No issues."),
            label="pass" if score >= 0.5 else "fail",
        )]


class SOPCompletionEvaluator(Evaluator[str, str]):
    """Evaluates whether the agent completed the SOP's key steps.

    Uses metadata.required_tools to check that expected tools were called.
    Uses metadata.success_pattern to check the final output.
    """

    def evaluate(self, case: EvaluationData[str, str]) -> list[EvaluationOutput]:
        tool_spans = _extract_tool_spans(case.actual_trajectory)
        tools_called = {span.tool_call.name for span in tool_spans}
        output = str(case.actual_output or "")
        meta = case.metadata or {}

        issues = []

        # Check required tools were called
        # kubectl-family tools satisfy the "kubectl" requirement
        _KUBECTL_FAMILY = {"kubectl", "kubectl_exec", "check_pod_status", "get_pod_name", "get_pod_logs", "describe_node"}
        required = meta.get("required_tools", [])
        missing = []
        for t in required:
            if t == "kubectl":
                if not tools_called & _KUBECTL_FAMILY:
                    missing.append(t)
            elif t not in tools_called:
                missing.append(t)
        if missing:
            issues.append(f"Missing required tools: {missing}")

        # Check success pattern in output
        success_pattern = meta.get("success_pattern", "")
        if success_pattern and success_pattern not in output:
            issues.append(f"Success pattern '{success_pattern}' not found in output")

        # Check agent didn't crash (has some output)
        if not output.strip():
            issues.append("Empty agent output — likely crashed")

        # Check for failure markers in agent output
        failure_markers = [
            "CRITICAL FAILURE", "CANNOT EXECUTE", "CANNOT BE FULLY EXECUTED",
            "COMPLETELY FAILED", "Cannot fork", "EXECUTION BLOCKED",
            "Resource temporarily unavailable",
        ]
        found = [m for m in failure_markers if m in output]
        if found:
            issues.append(f"Agent reported failure: {found[0]}")

        # Score
        if not issues:
            score = 1.0
        else:
            score = max(0.0, 1.0 - 0.3 * len(issues))

        return [EvaluationOutput(
            score=score,
            test_pass=score >= 0.5,
            reason=" | ".join(issues) if issues else "SOP completed successfully.",
            label="pass" if score >= 0.5 else "fail",
        )]


class ExecutionTimeEvaluator(Evaluator[str, str]):
    """Evaluates whether execution completed within expected time budget.

    Expected time derived from SOP complexity: base 60s + 5s per bash block + 0.5s per line.
    """

    def evaluate(self, case: EvaluationData[str, str]) -> list[EvaluationOutput]:
        meta = case.metadata or {}
        bash_blocks = meta.get("bash_blocks", 0)
        lines = meta.get("lines", 0)
        execution_time_s = meta.get("execution_time_s", 0)

        if not execution_time_s:
            return [EvaluationOutput(
                score=0.5, test_pass=True,
                reason="No execution time recorded.",
                label="no_data",
            )]

        # Budget: base 60s + 5s per bash block + 0.5s per line, min 120s
        budget_s = max(120, 60 + bash_blocks * 5 + lines // 2)
        ratio = execution_time_s / budget_s

        if ratio <= 1.0:
            score = 1.0
            reason = f"Completed in {execution_time_s:.0f}s (budget: {budget_s}s)"
        elif ratio <= 1.5:
            score = 0.7
            reason = f"Slow: {execution_time_s:.0f}s vs {budget_s}s budget (1.5x)"
        elif ratio <= 2.0:
            score = 0.4
            reason = f"Very slow: {execution_time_s:.0f}s vs {budget_s}s budget (2x)"
        else:
            score = 0.0
            reason = f"Timeout-level: {execution_time_s:.0f}s vs {budget_s}s budget ({ratio:.1f}x)"

        return [EvaluationOutput(
            score=score,
            test_pass=score >= 0.5,
            reason=reason,
            label="pass" if score >= 0.5 else "fail",
        )]


class ToolSuccessRateEvaluator(Evaluator[str, str]):
    """Evaluates the ratio of successful vs failed tool calls.

    A high failure rate indicates the agent is flailing — trying commands
    that don't work instead of reasoning about the right approach.
    """

    def evaluate(self, case: EvaluationData[str, str]) -> list[EvaluationOutput]:
        tool_spans = _extract_tool_spans(case.actual_trajectory)
        if not tool_spans:
            return [EvaluationOutput(
                score=0.5, test_pass=True,
                reason="No tool spans captured.",
                label="no_data",
            )]

        total = len(tool_spans)
        failed = sum(1 for s in tool_spans if s.tool_result and s.tool_result.error)
        success_rate = (total - failed) / total if total else 1.0

        if success_rate >= 0.8:
            score = 1.0
        elif success_rate >= 0.6:
            score = 0.7
        elif success_rate >= 0.4:
            score = 0.4
        else:
            score = 0.0

        reason = f"{total - failed}/{total} tool calls succeeded ({success_rate:.0%})"
        if failed:
            # Find most common error
            error_counts: dict[str, int] = {}
            for s in tool_spans:
                if s.tool_result and s.tool_result.error:
                    key = f"{s.tool_call.name}: {s.tool_result.error[:80]}"
                    error_counts[key] = error_counts.get(key, 0) + 1
            top_error = max(error_counts, key=error_counts.get) if error_counts else ""
            reason += f" | Top error: {top_error}"

        return [EvaluationOutput(
            score=score,
            test_pass=score >= 0.5,
            reason=reason,
            label="pass" if score >= 0.5 else "fail",
        )]
