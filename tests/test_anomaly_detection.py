# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Tests for agents/anra/monitoring/anomaly_detection.py."""
from unittest.mock import patch

import pytest

from amzn_cse_telco_autonomous_network_agents_app.agent.agents.anra.monitoring import (
    anomaly_detection,
)
from amzn_cse_telco_autonomous_network_agents_app.agent.agents.anra.monitoring.anomaly_detection import _baselines, evaluate_dynamic_anomalies, reset_baselines


@pytest.fixture(autouse=True)
def _isolate_module_state():
    """Snapshot and restore the module's rolling-baseline and rate-limit globals.

    evaluate_dynamic_anomalies mutates _baselines, and several tests write
    _bedrock_last_classify directly to force a code path. Save/restore both here
    so no test's mutation leaks into another regardless of run order.
    """
    saved_baselines = {k: dict(v) for k, v in anomaly_detection._baselines.items()}
    saved_last_classify = anomaly_detection._bedrock_last_classify
    reset_baselines()
    try:
        yield
    finally:
        anomaly_detection._baselines.clear()
        anomaly_detection._baselines.update(saved_baselines)
        anomaly_detection._bedrock_last_classify = saved_last_classify


class TestBaselineAccumulation:
    @patch("amzn_cse_telco_autonomous_network_agents_app.agent.agents.kpi_monitor.influx_source.query_influx_all")
    def test_no_anomaly_below_10_samples(self, mock_query):
        """Need at least 10 samples before detecting anomalies."""
        mock_query.return_value = {"cpu": 50.0}
        for _ in range(9):
            result = evaluate_dynamic_anomalies()
        assert result == []

    @patch("amzn_cse_telco_autonomous_network_agents_app.agent.agents.kpi_monitor.influx_source.query_influx_all")
    def test_stable_metric_no_anomaly(self, mock_query):
        """Stable values should not trigger anomalies."""
        mock_query.return_value = {"cpu": 50.0}
        for _ in range(15):
            evaluate_dynamic_anomalies()
        # Still 50 -- no deviation
        result = evaluate_dynamic_anomalies()
        assert result == []

    @patch("amzn_cse_telco_autonomous_network_agents_app.agent.agents.kpi_monitor.influx_source.query_influx_all")
    @patch("amzn_cse_telco_autonomous_network_agents_app.agent.agents.anra.monitoring.anomaly_detection._classify_anomalies")
    def test_spike_triggers_anomaly(self, mock_classify, mock_query):
        """A value >3 sigma from baseline should be flagged."""
        mock_classify.return_value = [{"name": "test_alarm", "severity": "warning", "source": "dynamic-anomaly"}]
        # Build baseline with stable values
        mock_query.return_value = {"cpu": 50.0}
        for _ in range(20):
            evaluate_dynamic_anomalies()
        # Inject spike
        mock_query.return_value = {"cpu": 500.0}
        # Reset cooldown
        import amzn_cse_telco_autonomous_network_agents_app.agent.agents.anra.monitoring.anomaly_detection as mod
        mod._bedrock_last_classify = 0
        result = evaluate_dynamic_anomalies()
        assert len(result) == 1
        mock_classify.assert_called_once()

    @patch("amzn_cse_telco_autonomous_network_agents_app.agent.agents.kpi_monitor.influx_source.query_influx_all")
    def test_empty_metrics_returns_empty(self, mock_query):
        mock_query.return_value = {}
        assert evaluate_dynamic_anomalies() == []

    @patch("amzn_cse_telco_autonomous_network_agents_app.agent.agents.kpi_monitor.influx_source.query_influx_all")
    def test_non_numeric_skipped(self, mock_query):
        mock_query.return_value = {"status": "ok", "cpu": 50.0}
        for _ in range(15):
            evaluate_dynamic_anomalies()
        assert "status" not in _baselines

    @patch("amzn_cse_telco_autonomous_network_agents_app.agent.agents.kpi_monitor.influx_source.query_influx_all")
    def test_cooldown_prevents_repeated_classification(self, mock_query):
        """Bedrock classification is rate-limited."""
        import amzn_cse_telco_autonomous_network_agents_app.agent.agents.anra.monitoring.anomaly_detection as mod
        import time

        mock_query.return_value = {"cpu": 50.0}
        for _ in range(20):
            evaluate_dynamic_anomalies()
        # Set last classify to now (simulating recent call)
        mod._bedrock_last_classify = time.time()
        mock_query.return_value = {"cpu": 500.0}
        result = evaluate_dynamic_anomalies()
        # Should return empty due to cooldown
        assert result == []


class TestResetBaselines:
    def test_reset_clears_state(self):
        _baselines["test"] = {"count": 100, "sum": 5000, "sum_sq": 250000}
        reset_baselines()
        assert len(_baselines) == 0


class TestCanonicalBehaviors:
    """Lock in the two behaviors that made monitor's copy canonical over the
    earlier twin (the twin had dropped both): the known-threshold-field
    suppression gate and the per-cycle cap on anomalies sent to Bedrock."""

    @patch("amzn_cse_telco_autonomous_network_agents_app.agent.agents.kpi_monitor.influx_source.query_influx_all")
    @patch("amzn_cse_telco_autonomous_network_agents_app.agent.agents.anra.monitoring.anomaly_detection._classify_anomalies")
    def test_known_threshold_field_is_suppressed(self, mock_classify, mock_query):
        # A field that already has an explicit threshold rule must NOT be routed
        # to Bedrock classification (it's handled by the threshold path).
        import amzn_cse_telco_autonomous_network_agents_app.agent.agents.anra.monitoring.anomaly_detection as mod

        field = next(iter(mod._KNOWN_THRESHOLD_FIELDS))
        mock_query.return_value = {field: 50.0}
        for _ in range(20):
            evaluate_dynamic_anomalies()
        mod._bedrock_last_classify = 0
        # Spike the known field: it deviates >3 sigma but must be suppressed.
        mock_query.return_value = {field: 500.0}
        result = evaluate_dynamic_anomalies()
        assert result == []
        mock_classify.assert_not_called()

    @patch("amzn_cse_telco_autonomous_network_agents_app.agent.agents.kpi_monitor.influx_source.query_influx_all")
    @patch("amzn_cse_telco_autonomous_network_agents_app.agent.agents.anra.monitoring.anomaly_detection._classify_anomalies")
    def test_anomalies_sent_to_bedrock_are_capped(self, mock_classify, mock_query):
        import amzn_cse_telco_autonomous_network_agents_app.agent.agents.anra.monitoring.anomaly_detection as mod

        mock_classify.return_value = []
        n = mod._MAX_ANOMALIES_PER_CLASSIFY + 5  # more than the cap
        # Build a stable baseline for n unknown fields.
        mock_query.return_value = {f"unknown_metric_{i}": 50.0 for i in range(n)}
        for _ in range(20):
            evaluate_dynamic_anomalies()
        mod._bedrock_last_classify = 0
        # Spike all of them at once.
        mock_query.return_value = {f"unknown_metric_{i}": 500.0 for i in range(n)}
        evaluate_dynamic_anomalies()
        mock_classify.assert_called_once()
        passed = mock_classify.call_args.args[0]
        assert len(passed) == mod._MAX_ANOMALIES_PER_CLASSIFY
