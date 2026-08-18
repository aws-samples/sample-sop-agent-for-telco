# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Unit tests for auto-investigation of escalating trends."""

import sys
from unittest.mock import MagicMock, patch

sys.modules.setdefault("strands", MagicMock())

from amzn_cse_telco_autonomous_network_agents_app.agent.agents.kpi_monitor.auto_investigate import (
    clear_investigated,
    maybe_investigate_trend,
)


class TestMaybeInvestigateTrend:
    def setup_method(self):
        clear_investigated()

    @patch("amzn_cse_telco_autonomous_network_agents_app.agent.monitor._submit_sop")
    def test_triggers_investigation_for_escalating_alarm(self, mock_submit):
        escalating = [
            {"alarm": "ptp_drift", "last_24h": 15, "prev_24h": 5, "ratio": 3.0, "total_7d": 40}
        ]
        triggered = maybe_investigate_trend(escalating)

        assert triggered == ["ptp_drift"]
        mock_submit.assert_called_once()
        alert_arg = mock_submit.call_args[0][0]
        assert alert_arg["name"] == "trend_escalating_ptp_drift"
        assert alert_arg["source"] == "trend-detection"
        assert "3.0x" in alert_arg["service_impact"]

    @patch("amzn_cse_telco_autonomous_network_agents_app.agent.monitor._submit_sop")
    def test_cooldown_prevents_repeated_investigation(self, mock_submit):
        escalating = [
            {"alarm": "ptp_drift", "last_24h": 15, "prev_24h": 5, "ratio": 3.0, "total_7d": 40}
        ]

        # First call triggers
        maybe_investigate_trend(escalating)
        assert mock_submit.call_count == 1

        # Second call within cooldown does NOT trigger
        maybe_investigate_trend(escalating)
        assert mock_submit.call_count == 1

    @patch("amzn_cse_telco_autonomous_network_agents_app.agent.monitor._submit_sop")
    def test_multiple_alarms_investigated_independently(self, mock_submit):
        escalating = [
            {"alarm": "ptp_drift", "last_24h": 15, "prev_24h": 5, "ratio": 3.0, "total_7d": 40},
            {"alarm": "du_cpu_overload", "last_24h": 10, "prev_24h": 3, "ratio": 3.3, "total_7d": 25},
        ]
        triggered = maybe_investigate_trend(escalating)

        assert set(triggered) == {"ptp_drift", "du_cpu_overload"}
        assert mock_submit.call_count == 2

    @patch("amzn_cse_telco_autonomous_network_agents_app.agent.monitor._submit_sop")
    def test_submit_failure_does_not_crash(self, mock_submit):
        mock_submit.side_effect = RuntimeError("monitor not loaded")
        escalating = [
            {"alarm": "ptp_drift", "last_24h": 15, "prev_24h": 5, "ratio": 3.0, "total_7d": 40}
        ]
        # Should not raise
        triggered = maybe_investigate_trend(escalating)
        assert triggered == ["ptp_drift"]
