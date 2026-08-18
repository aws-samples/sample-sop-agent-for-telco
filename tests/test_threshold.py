# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Tests for agents/kpi_monitor/threshold.py — condition evaluation and config-driven thresholds."""



from amzn_cse_telco_autonomous_network_agents_app.agent.agents.kpi_monitor.threshold import (
    _eval_condition,
)


class TestEvalCondition:
    """Test all comparison operators."""

    def test_greater_than_true(self):
        assert _eval_condition(85, "> 80") is True

    def test_greater_than_false(self):
        assert _eval_condition(79, "> 80") is False

    def test_greater_than_boundary(self):
        assert _eval_condition(80, "> 80") is False

    def test_less_than_true(self):
        assert _eval_condition(0.5, "< 1") is True

    def test_less_than_false(self):
        assert _eval_condition(2, "< 1") is False

    def test_less_than_boundary(self):
        assert _eval_condition(1, "< 1") is False

    def test_greater_equal_true(self):
        assert _eval_condition(80, ">= 80") is True

    def test_greater_equal_above(self):
        assert _eval_condition(81, ">= 80") is True

    def test_greater_equal_below(self):
        assert _eval_condition(79, ">= 80") is False

    def test_less_equal_true(self):
        assert _eval_condition(1, "<= 1") is True

    def test_less_equal_below(self):
        assert _eval_condition(0, "<= 1") is True

    def test_less_equal_above(self):
        assert _eval_condition(2, "<= 1") is False

    def test_equal_true(self):
        assert _eval_condition(0, "== 0") is True

    def test_equal_false(self):
        assert _eval_condition(1, "== 0") is False

    def test_float_threshold(self):
        assert _eval_condition(1500.1, "> 1500") is True

    def test_negative_value(self):
        assert _eval_condition(-5, "< 0") is True

    def test_large_value(self):
        assert _eval_condition(66_000_000, "> 500000") is True


class TestEvalConditionEdgeCases:
    def test_whitespace_handling(self):
        assert _eval_condition(85, "  >  80  ") is True

    def test_float_precision(self):
        assert _eval_condition(0.0, "== 0") is True

    def test_zero_threshold(self):
        assert _eval_condition(0, "> 0") is False
        assert _eval_condition(1, "> 0") is True
