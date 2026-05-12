# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Tests for the workshop branch monitor module."""
import pytest
from unittest.mock import patch, MagicMock

from monitor import (
    _eval_condition,
    resolve_sop,
    _run,
    evaluate_thresholds,
    evaluate_ran_thresholds,
    evaluate_os_thresholds,
)


class TestEvalCondition:
    def test_gt_true(self):
        assert _eval_condition(10, "> 5") is True

    def test_gt_false(self):
        assert _eval_condition(3, "> 5") is False

    def test_lt_true(self):
        assert _eval_condition(3, "< 5") is True

    def test_lt_false(self):
        assert _eval_condition(10, "< 5") is False

    def test_eq_true(self):
        assert _eval_condition(5, "== 5") is True

    def test_eq_false(self):
        assert _eval_condition(3, "== 5") is False

    def test_gte(self):
        assert _eval_condition(5, ">= 5") is True
        assert _eval_condition(4, ">= 5") is False

    def test_lte(self):
        assert _eval_condition(5, "<= 5") is True
        assert _eval_condition(6, "<= 5") is False

    def test_invalid_operator_returns_false(self):
        assert _eval_condition(5, "invalid 5") is False


class TestResolveSop:
    def test_returns_string_or_none(self):
        result = resolve_sop({"name": "nf_crashloop"})
        assert result is None or isinstance(result, str)

    def test_unknown_alarm_returns_none(self):
        result = resolve_sop({"name": "nonexistent_alarm_xyz"})
        assert result is None


class TestEvaluateThresholds:
    @patch("monitor._run")
    def test_returns_list(self, mock_run):
        mock_run.return_value = ""
        result = evaluate_thresholds()
        assert isinstance(result, list)

    @patch("monitor._run")
    def test_no_crash_on_kubectl_failure(self, mock_run):
        mock_run.return_value = "connection refused"
        # Should not raise
        evaluate_thresholds()


class TestRun:
    @patch("subprocess.run")
    def test_success(self, mock_subprocess):
        mock_subprocess.return_value = MagicMock(
            returncode=0, stdout="output", stderr=""
        )
        result = _run("echo hello")
        assert isinstance(result, str)
        assert "output" in result or result == "output"

    @patch("subprocess.run")
    def test_failure(self, mock_subprocess):
        mock_subprocess.return_value = MagicMock(
            returncode=1, stdout="", stderr="error"
        )
        result = _run("false")
        assert isinstance(result, str)
