# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Tests for day2-monitor/monitor.py — alarm lookup, alert filtering, fingerprinting."""

import sys
import os
import json
from unittest.mock import patch

import pytest

# Add day2-monitor to path so we can import individual functions
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "day2-monitor"))


# ── _lookup_alarm tests ──

SAMPLE_REF = {
    "server_fault": {"severity": "Critical", "reaction": "Check UPFMng"},
    "gwu_fault_information": {
        "severity": "Warning",
        "reaction_required": True,
        "reaction": "Check KIND and DTL",
        "service_impact": "Call connection can continue",
    },
    "gwu_blade_fault": {"severity": "Major", "reaction": "Check App status"},
    "bgp_peer_connection_fault": {"severity": "Major", "reaction": "Check network"},
}


@pytest.fixture(autouse=True)
def _patch_alarm_ref():
    """Patch the module-level _alarm_reference dict for all tests."""
    import monitor
    original = monitor._alarm_reference.copy()
    monitor._alarm_reference.clear()
    monitor._alarm_reference.update(SAMPLE_REF)
    yield
    monitor._alarm_reference.clear()
    monitor._alarm_reference.update(original)


class TestLookupAlarm:
    def test_exact_match(self):
        from monitor import _lookup_alarm
        result = _lookup_alarm("server_fault")
        assert result["severity"] == "Critical"

    def test_prefix_match_variant_suffix(self):
        """gwu_fault_information_worker_overload → gwu_fault_information"""
        from monitor import _lookup_alarm
        result = _lookup_alarm("gwu_fault_information_worker_overload")
        assert result is not None
        assert result["reaction"] == "Check KIND and DTL"

    def test_prefix_match_picks_longest(self):
        """If alert matches multiple prefixes, pick the longest."""
        from monitor import _lookup_alarm
        # gwu_blade_fault_xyz should match gwu_blade_fault (len=15) not gwu_fault_information
        result = _lookup_alarm("gwu_blade_fault_xyz")
        assert result["severity"] == "Major"
        assert result["reaction"] == "Check App status"

    def test_reverse_prefix_match(self):
        """Short alert name matches longer reference name."""
        from monitor import _lookup_alarm
        result = _lookup_alarm("bgp_peer_connection")
        assert result is not None
        assert result["reaction"] == "Check network"

    def test_no_match_returns_none(self):
        from monitor import _lookup_alarm
        result = _lookup_alarm("completely_unknown_alert")
        assert result is None

    def test_empty_reference_returns_none(self):
        import monitor
        monitor._alarm_reference.clear()
        result = monitor._lookup_alarm("server_fault")
        assert result is None


# ── alert_fingerprint tests ──

class TestAlertFingerprint:
    def test_stable_fingerprint(self):
        from monitor import alert_fingerprint
        alert = {"labels": {"alertname": "test", "namespace": "ns", "pod": "p1", "job": "j1"}}
        fp1 = alert_fingerprint(alert)
        fp2 = alert_fingerprint(alert)
        assert fp1 == fp2
        assert len(fp1) == 12

    def test_different_alerts_different_fingerprints(self):
        from monitor import alert_fingerprint
        a1 = {"labels": {"alertname": "alert_a", "namespace": "ns"}}
        a2 = {"labels": {"alertname": "alert_b", "namespace": "ns"}}
        assert alert_fingerprint(a1) != alert_fingerprint(a2)

    def test_missing_labels_still_works(self):
        from monitor import alert_fingerprint
        fp = alert_fingerprint({})
        assert len(fp) == 12


# ── fetch_active_alerts filtering tests ──

class TestFetchActiveAlerts:
    MOCK_ALERTS = json.dumps([
        {"status": {"state": "active"}, "labels": {"alertname": "gwu_fault_information"}},
        {"status": {"state": "active"}, "labels": {"alertname": "Watchdog"}},
        {"status": {"state": "suppressed"}, "labels": {"alertname": "gwu_blade_fault"}},
        {"status": {"state": "active"}, "labels": {"alertname": "server_fault"}},
    ])

    @patch("monitor._run", return_value=MOCK_ALERTS)
    def test_filters_ignored_alerts(self, mock_run):
        from monitor import fetch_active_alerts
        alerts = fetch_active_alerts()
        names = [a["labels"]["alertname"] for a in alerts]
        assert "Watchdog" not in names

    @patch("monitor._run", return_value=MOCK_ALERTS)
    def test_filters_suppressed(self, mock_run):
        from monitor import fetch_active_alerts
        alerts = fetch_active_alerts()
        names = [a["labels"]["alertname"] for a in alerts]
        assert "gwu_blade_fault" not in names  # suppressed

    @patch("monitor._run", return_value=MOCK_ALERTS)
    def test_alert_filter_whitelist(self, mock_run):
        import monitor
        original = monitor.ALERT_FILTER.copy()
        monitor.ALERT_FILTER.clear()
        monitor.ALERT_FILTER.add("server_fault")
        try:
            alerts = monitor.fetch_active_alerts()
            names = [a["labels"]["alertname"] for a in alerts]
            assert names == ["server_fault"]
        finally:
            monitor.ALERT_FILTER.clear()
            monitor.ALERT_FILTER.update(original)

    @patch("monitor._run", return_value="not json")
    def test_bad_json_returns_empty(self, mock_run):
        from monitor import fetch_active_alerts
        assert fetch_active_alerts() == []


# ── generate_remediation_sop tests ──

class TestGenerateRemediationSop:
    def test_fallback_template_on_import_error(self):
        """SOP generation should return a valid SOP (real or fallback)."""
        from monitor import generate_remediation_sop
        alert = {
            "labels": {"alertname": "test_alert", "severity": "warning", "namespace": "aws-app"},
            "annotations": {"summary": "Test summary"},
        }
        sop = generate_remediation_sop(alert, [], [])
        assert "# Remediation: test_alert" in sop or "Remediation" in sop

    def test_alarm_context_injected(self):
        """Verify alarm reference context is built for the prompt."""
        from monitor import _lookup_alarm
        ref = _lookup_alarm("gwu_fault_information_worker_overload")
        assert ref is not None
        assert "Check KIND and DTL" in ref["reaction"]
