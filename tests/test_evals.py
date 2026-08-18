# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Tests for evals/ — evaluators and SOP corrector."""

import sys
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent / "evals"))

from sop_corrector import (
    CORRECTOR_PROMPT,
    MAX_CORRECTIONS_PER_SESSION,
    build_correction_prompt,
    extract_failures,
)


class TestCorrectorPrompt:
    def test_prompt_not_empty(self):
        assert len(CORRECTOR_PROMPT) > 100

    def test_prompt_has_rules(self):
        assert "Rules:" in CORRECTOR_PROMPT

    def test_max_corrections_reasonable(self):
        assert 1 <= MAX_CORRECTIONS_PER_SESSION <= 5


class TestExtractFailures:
    def test_extracts_failures(self):
        report = MagicMock()
        report.evaluator_name = "SOPCompletionEvaluator"
        report.test_passes = [True, False, False]
        report.reasons = ["ok", "Missing tools: [kubectl]", "Empty output"]
        report.scores = [1.0, 0.3, 0.0]
        failures = extract_failures([report])
        assert len(failures) == 2
        assert failures[0]["evaluator"] == "SOPCompletionEvaluator"
        assert "Missing tools" in failures[0]["reason"]

    def test_no_failures(self):
        report = MagicMock()
        report.test_passes = [True, True]
        report.reasons = ["ok", "ok"]
        report.scores = [1.0, 1.0]
        assert extract_failures([report]) == []

    def test_multiple_reports(self):
        r1 = MagicMock()
        r1.evaluator_name = "A"
        r1.test_passes = [False]
        r1.reasons = ["fail1"]
        r1.scores = [0.0]
        r2 = MagicMock()
        r2.evaluator_name = "B"
        r2.test_passes = [False]
        r2.reasons = ["fail2"]
        r2.scores = [0.2]
        failures = extract_failures([r1, r2])
        assert len(failures) == 2


class TestBuildCorrectionPrompt:
    def test_includes_failures(self):
        prompt = build_correction_prompt("# My SOP", [{"evaluator": "E", "reason": "broken"}])
        assert "broken" in prompt
        assert "# My SOP" in prompt

    def test_includes_sop_content(self):
        prompt = build_correction_prompt("## Step 1\n```bash\nkubectl get pods\n```", [])
        assert "kubectl get pods" in prompt


class TestCorrectSopRateLimit:
    def test_rate_limits_corrections(self, tmp_path):
        sop = tmp_path / "test.md"
        sop.write_text("# Test SOP")
        report = MagicMock()
        report.evaluator_name = "E"
        report.test_passes = [False]
        report.reasons = ["fail"]
        report.scores = [0.0]

        counter = {"test": MAX_CORRECTIONS_PER_SESSION}
        from sop_corrector import correct_sop

        result = correct_sop([report], str(sop), _correction_count=counter)
        assert result is None  # rate limited

    def test_no_failures_returns_none(self, tmp_path):
        sop = tmp_path / "test.md"
        sop.write_text("# Test SOP")
        report = MagicMock()
        report.test_passes = [True]
        report.reasons = ["ok"]
        report.scores = [1.0]
        from sop_corrector import correct_sop

        result = correct_sop([report], str(sop))
        assert result is None


class TestEvaluatorsImport:
    """Verify evaluator classes are importable and have correct interface."""

    def test_import_all_evaluators(self):
        from evaluators import (
            ExecutionTimeEvaluator,
            SOPCompletionEvaluator,
            SteeringEffectivenessEvaluator,
            ToolSuccessRateEvaluator,
        )

        assert callable(SteeringEffectivenessEvaluator)
        assert callable(SOPCompletionEvaluator)
        assert callable(ExecutionTimeEvaluator)
        assert callable(ToolSuccessRateEvaluator)

    def test_extract_tool_spans_empty(self):
        from evaluators import _extract_tool_spans

        assert _extract_tool_spans(None) == []
        assert _extract_tool_spans("not a session") == []

    def test_evaluators_have_evaluate_method(self):
        from evaluators import SOPCompletionEvaluator, SteeringEffectivenessEvaluator

        assert hasattr(SOPCompletionEvaluator(), "evaluate")
        assert hasattr(SteeringEffectivenessEvaluator(), "evaluate")


class TestSOPCompletionEvaluator:
    def test_empty_output_flagged(self):
        from evaluators import SOPCompletionEvaluator

        evaluator = SOPCompletionEvaluator()
        case = MagicMock()
        case.actual_trajectory = None
        case.actual_output = ""
        case.metadata = {}
        results = evaluator.evaluate(case)
        assert any("Empty" in r.reason for r in results)

    def test_failure_marker_detected(self):
        from evaluators import SOPCompletionEvaluator

        evaluator = SOPCompletionEvaluator()
        case = MagicMock()
        case.actual_trajectory = None
        case.actual_output = "CRITICAL FAILURE: cannot connect"
        case.metadata = {}
        results = evaluator.evaluate(case)
        assert any("failure" in r.reason.lower() for r in results)

    def test_no_issues_passes(self):
        from evaluators import SOPCompletionEvaluator

        evaluator = SOPCompletionEvaluator()
        case = MagicMock()
        case.actual_trajectory = None
        case.actual_output = "All steps completed successfully."
        case.metadata = {}
        results = evaluator.evaluate(case)
        assert all(r.test_pass for r in results)


class TestSteeringEffectivenessEvaluator:
    def test_no_spans_returns_neutral(self):
        from evaluators import SteeringEffectivenessEvaluator

        evaluator = SteeringEffectivenessEvaluator()
        case = MagicMock()
        case.actual_trajectory = None
        case.metadata = {}
        results = evaluator.evaluate(case)
        assert results[0].test_pass is True
        assert results[0].score == 0.5


class TestExecutionTimeEvaluator:
    def test_no_time_recorded(self):
        from evaluators import ExecutionTimeEvaluator

        evaluator = ExecutionTimeEvaluator()
        case = MagicMock()
        case.metadata = {}
        results = evaluator.evaluate(case)
        assert results[0].test_pass is True

    def test_within_budget(self):
        from evaluators import ExecutionTimeEvaluator

        evaluator = ExecutionTimeEvaluator()
        case = MagicMock()
        case.metadata = {"execution_time_s": 60, "bash_blocks": 5, "lines": 50}
        results = evaluator.evaluate(case)
        assert results[0].score == 1.0

    def test_over_budget(self):
        from evaluators import ExecutionTimeEvaluator

        evaluator = ExecutionTimeEvaluator()
        case = MagicMock()
        case.metadata = {"execution_time_s": 500, "bash_blocks": 3, "lines": 20}
        results = evaluator.evaluate(case)
        assert results[0].score < 1.0
