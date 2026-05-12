# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Custom evaluators for SOP execution — built on Strands Evals SDK."""

from strands_evals.evaluators import Evaluator
from strands_evals.types.evaluation import EvaluationData, EvaluationOutput
from typing_extensions import TypeVar

InputT = TypeVar("InputT")
OutputT = TypeVar("OutputT")


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


class SteeringEffectivenessEvaluator(Evaluator[InputT, OutputT]):
    """Evaluates whether the agent stayed within tool budget and followed steering."""

    def evaluate(self, evaluation_case: EvaluationData[InputT, OutputT]) -> list[EvaluationOutput]:
        trajectory = evaluation_case.actual_trajectory
        tool_spans = _extract_tool_spans(trajectory)
        tool_count = len(tool_spans)
        metadata = evaluation_case.metadata or {}
        budget = metadata.get("tool_budget", 95)

        if tool_count >= budget:
            return [
                EvaluationOutput(
                    score=0.0, test_pass=False, reason=f"Tool budget exceeded: {tool_count}/{budget} calls."
                )
            ]
        if tool_count > budget * 0.8:
            return [
                EvaluationOutput(
                    score=0.5, test_pass=True, reason=f"⚠️ {tool_count} tool calls. Approaching budget ({budget})."
                )
            ]
        return [EvaluationOutput(score=1.0, test_pass=True, reason=f"✅ {tool_count} tool calls. No issues.")]

    async def evaluate_async(self, evaluation_case: EvaluationData[InputT, OutputT]) -> list[EvaluationOutput]:
        return self.evaluate(evaluation_case)


class SOPCompletionEvaluator(Evaluator[InputT, OutputT]):
    """Evaluates whether the SOP completed successfully."""

    def evaluate(self, evaluation_case: EvaluationData[InputT, OutputT]) -> list[EvaluationOutput]:
        output = str(evaluation_case.actual_output or "")
        lower = output.lower()

        if "all steps complete" in lower or "✅" in output:
            return [EvaluationOutput(score=1.0, test_pass=True, reason="✅ SOP completed successfully.")]
        if "failure" in lower or "❌" in output:
            return [EvaluationOutput(score=0.0, test_pass=False, reason="❌ SOP had failures.")]
        return [EvaluationOutput(score=0.5, test_pass=True, reason="⚠️ SOP completion unclear from output.")]

    async def evaluate_async(self, evaluation_case: EvaluationData[InputT, OutputT]) -> list[EvaluationOutput]:
        return self.evaluate(evaluation_case)


class ExecutionTimeEvaluator(Evaluator[InputT, OutputT]):
    """Evaluates whether execution time is within acceptable bounds."""

    def evaluate(self, evaluation_case: EvaluationData[InputT, OutputT]) -> list[EvaluationOutput]:
        metadata = evaluation_case.metadata or {}
        exec_time = metadata.get("execution_time_s", 0)
        bash_blocks = metadata.get("bash_blocks", 5)
        budget = max(bash_blocks * 60, 120)

        if exec_time > budget:
            return [
                EvaluationOutput(
                    score=0.0, test_pass=False, reason=f"❌ Execution took {exec_time:.0f}s (budget: {budget}s)."
                )
            ]
        return [
            EvaluationOutput(
                score=1.0, test_pass=True, reason=f"✅ Execution took {exec_time:.0f}s (budget: {budget}s)."
            )
        ]

    async def evaluate_async(self, evaluation_case: EvaluationData[InputT, OutputT]) -> list[EvaluationOutput]:
        return self.evaluate(evaluation_case)


class ToolSuccessRateEvaluator(Evaluator[InputT, OutputT]):
    """Evaluates the success rate of tool calls."""

    def evaluate(self, evaluation_case: EvaluationData[InputT, OutputT]) -> list[EvaluationOutput]:
        trajectory = evaluation_case.actual_trajectory
        tool_spans = _extract_tool_spans(trajectory)
        if not tool_spans:
            return [EvaluationOutput(score=1.0, test_pass=True, reason="✅ No tool calls to evaluate.")]

        total = len(tool_spans)
        failed = sum(
            1
            for s in tool_spans
            if "error" in str(getattr(s, "attributes", {})).lower()
            or "failed" in str(getattr(s, "attributes", {})).lower()
        )
        success_rate = (total - failed) / total if total > 0 else 1.0

        if success_rate < 0.5:
            return [
                EvaluationOutput(
                    score=0.0,
                    test_pass=False,
                    reason=f"❌ Tool success rate: {success_rate:.0%} ({failed}/{total} failed).",
                )
            ]
        if success_rate < 0.8:
            return [
                EvaluationOutput(
                    score=0.5,
                    test_pass=True,
                    reason=f"⚠️ Tool success rate: {success_rate:.0%} ({failed}/{total} failed).",
                )
            ]
        return [
            EvaluationOutput(
                score=1.0, test_pass=True, reason=f"✅ Tool success rate: {success_rate:.0%} ({total} calls)."
            )
        ]

    async def evaluate_async(self, evaluation_case: EvaluationData[InputT, OutputT]) -> list[EvaluationOutput]:
        return self.evaluate(evaluation_case)
