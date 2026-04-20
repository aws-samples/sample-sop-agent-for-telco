# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Tests for day2-monitor — alert dedup, fingerprinting, SOP generation dispatch."""
import sys
import os
import json
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent / "day2-monitor"))
from monitor import (
    alert_fingerprint,
    MonitorState,
    fetch_active_alerts,
    fetch_k8s_events,
    IGNORED_ALERTS,
)


class TestAlertFingerprint:
    def test_same_alert_same_fingerprint(self):
        a = {"labels": {"alertname": "KubePodCrashLooping", "namespace": "aws-app", "pod": "app-svc-0", "job": ""}}
        assert alert_fingerprint(a) == alert_fingerprint(a)

    def test_different_alerts_different_fingerprints(self):
        a = {"labels": {"alertname": "KubePodCrashLooping", "namespace": "aws-app", "pod": "app-svc-0", "job": ""}}
        b = {"labels": {"alertname": "KubeNodeNotReady", "namespace": "", "pod": "", "job": ""}}
        assert alert_fingerprint(a) != alert_fingerprint(b)

    def test_missing_labels_still_works(self):
        a = {"labels": {"alertname": "Foo"}}
        fp = alert_fingerprint(a)
        assert isinstance(fp, str) and len(fp) == 12


class TestMonitorState:
    def test_is_new_first_time(self):
        state = MonitorState.__new__(MonitorState)
        state.seen_fingerprints = {}
        state.pending_issues = {}
        state.remediation_dir = Path("/tmp/test-remediation")
        assert state.is_new("abc123") is True

    def test_is_new_second_time(self):
        state = MonitorState.__new__(MonitorState)
        state.seen_fingerprints = {}
        state.pending_issues = {}
        state.remediation_dir = Path("/tmp/test-remediation")
        state.is_new("abc123")
        assert state.is_new("abc123") is False

    def test_cleanup_stale_removes_resolved(self):
        state = MonitorState.__new__(MonitorState)
        state.seen_fingerprints = {"fp1": 1.0, "fp2": 2.0, "fp3": 3.0}
        state.pending_issues = {}
        state.remediation_dir = Path("/tmp/test-remediation")
        state.cleanup_stale({"fp1", "fp3"})  # fp2 is stale
        assert "fp2" not in state.seen_fingerprints
        assert "fp1" in state.seen_fingerprints
        assert "fp3" in state.seen_fingerprints


class TestFetchAlerts:
    @patch("monitor._run")
    def test_filters_inactive_and_ignored(self, mock_run):
        mock_run.return_value = json.dumps([
            {"status": {"state": "active"}, "labels": {"alertname": "RealAlert", "severity": "warning"}},
            {"status": {"state": "active"}, "labels": {"alertname": "Watchdog"}},
            {"status": {"state": "suppressed"}, "labels": {"alertname": "Suppressed"}},
        ])
        alerts = fetch_active_alerts()
        assert len(alerts) == 1
        assert alerts[0]["labels"]["alertname"] == "RealAlert"

    @patch("monitor._run")
    def test_handles_invalid_json(self, mock_run):
        mock_run.return_value = "(timeout)"
        assert fetch_active_alerts() == []

    @patch("monitor._run")
    def test_empty_response(self, mock_run):
        mock_run.return_value = "[]"
        assert fetch_active_alerts() == []


class TestFetchEvents:
    @patch("monitor._kubectl")
    def test_parses_events(self, mock_kubectl):
        mock_kubectl.return_value = json.dumps({
            "items": [{
                "reason": "BackOff",
                "message": "Back-off restarting failed container",
                "involvedObject": {"name": "app-svc-0"},
                "count": 5,
                "lastTimestamp": "2026-04-05T10:00:00Z",
            }]
        })
        events = fetch_k8s_events()
        assert len(events) >= 1
        assert events[0]["reason"] == "BackOff"

    @patch("monitor._kubectl")
    def test_handles_empty(self, mock_kubectl):
        mock_kubectl.return_value = '{"items": []}'
        assert fetch_k8s_events() == []
