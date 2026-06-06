# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Tests for the workshop branch monitor module."""
import time

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
        assert _eval_condition(10, "gt 5") is True

    def test_gt_false(self):
        assert _eval_condition(3, "gt 5") is False

    def test_lt_true(self):
        assert _eval_condition(3, "lt 5") is True

    def test_lt_false(self):
        assert _eval_condition(10, "lt 5") is False

    def test_eq_true(self):
        assert _eval_condition(5, "eq 5") is True

    def test_eq_false(self):
        assert _eval_condition(3, "eq 5") is False

    def test_gte(self):
        assert _eval_condition(5, "gte 5") is True
        assert _eval_condition(4, "gte 5") is False

    def test_lte(self):
        assert _eval_condition(5, "lte 5") is True
        assert _eval_condition(6, "lte 5") is False

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
        mock_run.return_value = MagicMock(success=False, output="")
        result = evaluate_thresholds()
        assert isinstance(result, list)

    @patch("monitor._run")
    def test_no_crash_on_kubectl_failure(self, mock_run):
        mock_run.return_value = MagicMock(success=False, output="connection refused")
        # Should not raise
        evaluate_thresholds()


class TestRun:
    @patch("subprocess.run")
    def test_success(self, mock_subprocess):
        mock_subprocess.return_value = MagicMock(
            returncode=0, stdout="output", stderr=""
        )
        result = _run("echo hello")
        assert result.success is True

    @patch("subprocess.run")
    def test_failure(self, mock_subprocess):
        mock_subprocess.return_value = MagicMock(
            returncode=1, stdout="", stderr="error"
        )
        result = _run("false")
        assert result.success is False


class TestYamlDrivenRules:
    """Tests for Task 1.2 — YAML-driven alarm rules in anra-config.yaml."""

    @patch("monitor._query_influx")
    @patch("config.load_config")
    def test_evaluate_thresholds_loads_yaml_rules(self, mock_cfg, mock_influx):
        """Config has alarms → returns rules (does not fall back to legacy)."""
        from config import AlarmRule, SiteConfig

        rule = AlarmRule(
            name="test_rule", source="ran",
            metric_field="cpu", condition="> 80", severity="warning",
            service_impact="test impact", probable_cause="test cause",
        )
        mock_cfg.return_value = SiteConfig(alarms=[rule])
        mock_influx.return_value = {"cpu": 90.0}
        result = evaluate_thresholds()
        assert len(result) == 1
        assert result[0]["name"] == "test_rule"

    @patch("monitor.evaluate_os_thresholds_legacy")
    @patch("monitor.evaluate_ran_thresholds_legacy")
    @patch("config.load_config")
    def test_evaluate_thresholds_falls_back_when_yaml_empty(self, mock_cfg, mock_ran, mock_os):
        """No alarms in config → falls back to legacy."""
        from config import SiteConfig

        mock_cfg.return_value = SiteConfig(alarms=[])
        mock_ran.return_value = []
        mock_os.return_value = []
        evaluate_thresholds()
        mock_ran.assert_called_once()
        mock_os.assert_called_once()

    def test_yaml_rules_match_legacy_rule_count(self):
        """anra-config.yaml has 11 alarm rules (RAN + Core + OS)."""
        import sys
        sys.path.insert(0, "agent")
        from config import load_config

        cfg = load_config("anra-config.yaml")
        assert len(cfg.alarms) == 11

    def test_yaml_rules_have_complete_metadata(self):
        """Every rule has severity + service_impact."""
        import sys
        sys.path.insert(0, "agent")
        from config import load_config

        cfg = load_config("anra-config.yaml")
        for alarm in cfg.alarms:
            assert alarm.severity in ("warning", "critical"), f"{alarm.name} missing severity"
            assert alarm.service_impact, f"{alarm.name} missing service_impact"


class TestAbsentFor:
    """Tests for Task 1.3 — absent_for condition operator."""

    def test_absent_for_fires_after_duration(self):
        """Metric last seen in the past beyond threshold → fires."""
        import monitor
        with monitor._metric_state_lock:
            monitor._metric_last_seen["foo"] = time.time() - 120
        # Override startup time so grace period is past
        old_startup = monitor._startup_time
        monitor._startup_time = time.time() - 200
        try:
            assert _eval_condition(None, "absent_for 30s", field_name="foo") is True
        finally:
            monitor._startup_time = old_startup

    def test_absent_for_does_not_fire_within_duration(self):
        """Metric last seen recently → does not fire."""
        import monitor
        with monitor._metric_state_lock:
            monitor._metric_last_seen["bar"] = time.time() - 5
        old_startup = monitor._startup_time
        monitor._startup_time = time.time() - 200
        try:
            assert _eval_condition(None, "absent_for 30s", field_name="bar") is False
        finally:
            monitor._startup_time = old_startup

    def test_absent_for_grace_period_after_startup(self):
        """Within first 60s of startup → always returns False."""
        import monitor
        old_startup = monitor._startup_time
        monitor._startup_time = time.time() - 10  # only 10s since startup
        try:
            assert _eval_condition(None, "absent_for 5s", field_name="grace_test") is False
        finally:
            monitor._startup_time = old_startup

    def test_absent_for_never_seen_after_grace(self):
        """Metric never seen + past grace → fires."""
        import monitor
        old_startup = monitor._startup_time
        monitor._startup_time = time.time() - 200
        try:
            with monitor._metric_state_lock:
                monitor._metric_last_seen.pop("never_seen_field", None)
            assert _eval_condition(None, "absent_for 30s", field_name="never_seen_field") is True
        finally:
            monitor._startup_time = old_startup

    def test_absent_for_duration_parsing_seconds(self):
        """'absent_for 30s' → 30 seconds threshold."""
        import monitor
        old_startup = monitor._startup_time
        monitor._startup_time = time.time() - 200
        with monitor._metric_state_lock:
            monitor._metric_last_seen["sec_test"] = time.time() - 31
        try:
            assert _eval_condition(None, "absent_for 30s", field_name="sec_test") is True
        finally:
            monitor._startup_time = old_startup

    def test_absent_for_duration_parsing_minutes(self):
        """'absent_for 5m' → 300 seconds threshold."""
        import monitor
        old_startup = monitor._startup_time
        monitor._startup_time = time.time() - 400
        with monitor._metric_state_lock:
            monitor._metric_last_seen["min_test"] = time.time() - 301
        try:
            assert _eval_condition(None, "absent_for 5m", field_name="min_test") is True
        finally:
            monitor._startup_time = old_startup

    def test_absent_for_invalid_duration_returns_false(self):
        """Malformed condition → False (don't crash)."""
        assert _eval_condition(None, "absent_for", field_name="x") is False
        assert _eval_condition(None, "absent_for badvalue", field_name="x") is False

    def test_eval_condition_dispatches_by_prefix(self):
        """'> 5' still works after refactor (backward compat)."""
        assert _eval_condition(85, "> 80") is True
        assert _eval_condition(75, "> 80") is False
