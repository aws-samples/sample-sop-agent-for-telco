# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Unit tests for alarm trend detection."""

import sys
from datetime import datetime, timedelta
from unittest.mock import MagicMock

sys.modules.setdefault("strands", MagicMock())

from amzn_cse_telco_autonomous_network_agents_app.agent.agents.kpi_monitor.trend import (
    clear_history,
    detect_escalating_alarms,
    get_alarm_frequency,
    record_alarm,
)


class TestRecordAlarm:
    def setup_method(self):
        clear_history()

    def test_records_alarm(self):
        record_alarm("du_cpu_overload")
        freq = get_alarm_frequency("du_cpu_overload")
        assert freq["last_1h"] == 1
        assert freq["last_7d"] == 1

    def test_prunes_old_entries(self):
        old_ts = datetime.utcnow() - timedelta(days=8)
        record_alarm("old_alarm", timestamp=old_ts)
        freq = get_alarm_frequency("old_alarm")
        assert freq["last_7d"] == 0


class TestDetectEscalatingAlarms:
    def setup_method(self):
        clear_history()

    def test_no_alarms_returns_empty(self):
        assert detect_escalating_alarms() == []

    def test_below_threshold_not_escalating(self):
        # Only 3 occurrences — below _MIN_OCCURRENCES
        now = datetime.utcnow()
        for i in range(3):
            record_alarm("minor_alarm", timestamp=now - timedelta(hours=i))
        assert detect_escalating_alarms() == []

    def test_detects_escalating_pattern(self):
        now = datetime.utcnow()
        # Previous 24h: 3 occurrences
        for i in range(3):
            record_alarm("ptp_drift", timestamp=now - timedelta(hours=30 + i))
        # Last 24h: 7 occurrences (>2x)
        for i in range(7):
            record_alarm("ptp_drift", timestamp=now - timedelta(hours=i + 1))

        result = detect_escalating_alarms()
        assert len(result) == 1
        assert result[0]["alarm"] == "ptp_drift"
        assert result[0]["last_24h"] == 7
        assert result[0]["prev_24h"] == 3
        assert result[0]["trend"] == "escalating"
        assert result[0]["ratio"] == 2.3

    def test_stable_alarm_not_escalating(self):
        now = datetime.utcnow()
        # Same rate in both windows
        for i in range(5):
            record_alarm("stable_alarm", timestamp=now - timedelta(hours=i + 1))
        for i in range(5):
            record_alarm("stable_alarm", timestamp=now - timedelta(hours=25 + i))

        result = detect_escalating_alarms()
        assert len(result) == 0

    def test_new_alarm_no_prev_window(self):
        now = datetime.utcnow()
        # 10 occurrences in last 24h, 0 in prev 24h
        for i in range(10):
            record_alarm("new_alarm", timestamp=now - timedelta(hours=i + 1))

        # prev_24h is 0, so division guard prevents false positive
        result = detect_escalating_alarms()
        assert len(result) == 0


class TestGetAlarmFrequency:
    def setup_method(self):
        clear_history()

    def test_unknown_alarm(self):
        freq = get_alarm_frequency("nonexistent")
        assert freq["last_1h"] == 0
        assert freq["last_24h"] == 0
        assert freq["last_7d"] == 0

    def test_time_windows(self):
        now = datetime.utcnow()
        record_alarm("test_alarm", timestamp=now - timedelta(minutes=30))
        record_alarm("test_alarm", timestamp=now - timedelta(hours=12))
        record_alarm("test_alarm", timestamp=now - timedelta(days=3))

        freq = get_alarm_frequency("test_alarm")
        assert freq["last_1h"] == 1
        assert freq["last_24h"] == 2
        assert freq["last_7d"] == 3
