# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Custom evaluators for SOP execution — built on Strands Evals SDK."""

from strands_evals import Evaluator


def _extract_tool_spans(session):
    """Extract tool call spans from an eval session."""
    tool_spans = []
    if not session:
        return tool_spans
    for trace in getattr(session, "traces", []):
        for span in getattr(trace, "spans", []):
            name = getattr(span, "name", "")
            if "tool" in name.lower():
                tool_spans.append(span)
    return tool_spans


class SteeringEffectivenessEvaluator(Evaluator):
    """Evaluates whether the agent stayed within tool budget and followed steering guidance."""

    def evaluate(self, case, result):
        tool_spans = _extract_tool_spans(result.get("trajectory"))
        tool_count = len(tool_spans)
        budget = case.metadata.get("tool_budget", 95)

        if tool_count >= budget:
            return self._result(
                score=0.0,
                passed=False,
                reason=f"Tool budget exceeded: {tool_count}/{budget} calls.",
            )
        if tool_count > budget * 0.8:
            return self._result(
                score=0.5,
                passed=True,
                reason=f"⚠️ {tool_count} tool calls. Approaching budget ({budget}).",
            )
        return self._result(
            score=1.0,
            passed=True,
            reason=f"✅ {tool_count} tool calls. No issues.",
        )

    def _result(self, score, passed, reason):
        return type("EvalResult", (), {
            "overall_score": score,
            "test_passes": [passed],
            "reasons": [reason],
            "evaluator_name": "SteeringEffectivenessEvaluator",
        })()


class SOPCompletionEvaluator(Evaluator):
    """Evaluates whether the SOP completed successfully."""

    def evaluate(self, case, result):
        output = str(result.get("output", ""))
        lower = output.lower()

        if "all steps complete" in lower or "✅" in output:
            return self._result(1.0, True, "✅ SOP completed successfully.")
        if "failure" in lower or "❌" in output:
            return self._result(0.0, False, "❌ SOP had failures.")
        return self._result(0.5, True, "⚠️ SOP completion unclear from output.")

    def _result(self, score, passed, reason):
        return type("EvalResult", (), {
            "overall_score": score,
            "test_passes": [passed],
            "reasons": [reason],
            "evaluator_name": "SOPCompletionEvaluator",
        })()


class ExecutionTimeEvaluator(Evaluator):
    """Evaluates whether execution time is within acceptable bounds."""

    def evaluate(self, case, result):
        exec_time = case.metadata.get("execution_time_s", 0)
        bash_blocks = case.metadata.get("bash_blocks", 5)
        # Allow ~60s per bash block as a rough budget
        budget = max(bash_blocks * 60, 120)

        if exec_time > budget:
            return self._result(
                0.0, False,
                f"❌ Execution took {exec_time:.0f}s (budget: {budget}s).",
            )
        return self._result(
            1.0, True,
            f"✅ Execution took {exec_time:.0f}s (budget: {budget}s).",
        )

    def _result(self, score, passed, reason):
        return type("EvalResult", (), {
            "overall_score": score,
            "test_passes": [passed],
            "reasons": [reason],
            "evaluator_name": "ExecutionTimeEvaluator",
        })()


class ToolSuccessRateEvaluator(Evaluator):
    """Evaluates the success rate of tool calls."""

    def evaluate(self, case, result):
        tool_spans = _extract_tool_spans(result.get("trajectory"))
        if not tool_spans:
            return self._result(1.0, True, "✅ No tool calls to evaluate.")

        total = len(tool_spans)
        failed = sum(
            1 for s in tool_spans
            if "error" in str(getattr(s, "attributes", {})).lower()
            or "failed" in str(getattr(s, "attributes", {})).lower()
        )
        success_rate = (total - failed) / total if total > 0 else 1.0

        if success_rate < 0.5:
            return self._result(0.0, False, f"❌ Tool success rate: {success_rate:.0%} ({failed}/{total} failed).")
        if success_rate < 0.8:
            return self._result(0.5, True, f"⚠️ Tool success rate: {success_rate:.0%} ({failed}/{total} failed).")
        return self._result(1.0, True, f"✅ Tool success rate: {success_rate:.0%} ({total} calls).")

    def _result(self, score, passed, reason):
        return type("EvalResult", (), {
            "overall_score": score,
            "test_passes": [passed],
            "reasons": [reason],
            "evaluator_name": "ToolSuccessRateEvaluator",
        })()
