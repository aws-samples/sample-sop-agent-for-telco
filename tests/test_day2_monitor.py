# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Tests for the workshop branch monitor."""
import pytest
from unittest.mock import patch, MagicMock

from monitor import (
    resolve_sop,
    _eval_condition,
    evaluate_thresholds,
)


def test_eval_condition_gt():
    assert _eval_condition(10, "> 5") is True
    assert _eval_condition(3, "> 5") is False


def test_eval_condition_lt():
    assert _eval_condition(3, "< 5") is True
    assert _eval_condition(10, "< 5") is False


def test_eval_condition_eq():
    assert _eval_condition(5, "== 5") is True
    assert _eval_condition(3, "== 5") is False


@patch("monitor._run")
def test_evaluate_thresholds_no_crash(mock_run):
    mock_run.return_value = MagicMock(success=False, output="error")
    # Should not raise even if kubectl fails
    result = evaluate_thresholds()
    assert isinstance(result, list)


def test_resolve_sop_known_alarm():
    alert = {"name": "nf_crashloop"}
    sop = resolve_sop(alert)
    # Should return a path or None, not crash
    assert sop is None or isinstance(sop, str)
