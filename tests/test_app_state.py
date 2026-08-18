# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Tests for in-memory state management — semantic behaviour.

After the thread-safety refactor (CR-281261845), bare collections (`_alarms`,
`_executions`, ...) are intentionally not re-exported from ``app_state``;
all callers go through ``push_*`` writers and ``snapshot_*`` readers under
a single module-level lock. These tests use the public API.

For test setup we reach into ``agent.core.state`` directly to reset the
singleton collections under the lock — the canonical module's docstring
explicitly permits this with an explanatory comment, and a unit test fixture
is exactly that case.

Concurrency invariants are covered separately by ``test_app_state_thread_safety.py``.
"""
from amzn_cse_telco_autonomous_network_agents_app.agent import app_state
from amzn_cse_telco_autonomous_network_agents_app.agent.core import state as _state


def _reset_state() -> None:
    """Clear every state singleton under the lock — the safe equivalent of
    the pre-refactor ``app_state._alarms.clear()`` setup pattern."""
    with _state._lock:
        _state._alarms.clear()
        _state._active_alarm_names.clear()
        _state._executions.clear()
        _state._correlations.clear()
        _state._pending_approvals.clear()
        _state._activity.clear()


class TestPushAlarm:
    def setup_method(self):
        _reset_state()

    def test_push_adds_alarm(self):
        app_state.push_alarm({"name": "test", "severity": "critical"})
        alarms = app_state.snapshot_alarms()
        assert len(alarms) == 1
        assert alarms[0]["name"] == "test"

    def test_push_adds_timestamp(self):
        app_state.push_alarm({"name": "test", "severity": "warning"})
        assert "timestamp" in app_state.snapshot_alarms()[0]

    def test_push_deduplicates_by_name(self):
        app_state.push_alarm({"name": "dup", "severity": "warning", "value": 1})
        app_state.push_alarm({"name": "dup", "severity": "critical", "value": 2})
        alarms = app_state.snapshot_alarms()
        assert len(alarms) == 1
        assert alarms[0]["severity"] == "critical"
        assert alarms[0]["value"] == 2

    def test_push_tracks_active_names(self):
        app_state.push_alarm({"name": "a", "severity": "warning"})
        app_state.push_alarm({"name": "b", "severity": "critical"})
        active = app_state.snapshot_active_alarm_names()
        assert "a" in active
        assert "b" in active

    def test_push_caps_at_200(self):
        for i in range(210):
            app_state.push_alarm({"name": f"alarm_{i}", "severity": "warning"})
        assert len(app_state.snapshot_alarms()) == 200

    def test_push_auto_classifies_3gpp(self):
        app_state.push_alarm({"name": "k8s_crashloopbackoff", "severity": "critical"})
        alarm = app_state.snapshot_alarms()[0]
        assert alarm.get("alarmType") == "processing-error-alarm"


class TestClearAlarms:
    def setup_method(self):
        _reset_state()

    def test_clear_updates_active_set(self):
        # Seed an active alarm, then a clear cycle should drop it and add the new name.
        app_state.push_alarm({"name": "old", "severity": "warning"})
        app_state.clear_alarms({"new_alarm"})
        active = app_state.snapshot_active_alarm_names()
        assert "old" not in active
        assert "new_alarm" in active

    def test_clear_with_empty_set(self):
        app_state.push_alarm({"name": "x", "severity": "warning"})
        app_state.clear_alarms(set())
        assert len(app_state.snapshot_active_alarm_names()) == 0


class TestPushExecution:
    def setup_method(self):
        _reset_state()

    def test_push_execution(self):
        app_state.push_execution({"alarm": "test", "result": "completed"})
        execs = app_state.snapshot_executions()
        assert len(execs) == 1
        assert "timestamp" in execs[0]


class TestPushCorrelation:
    def setup_method(self):
        _reset_state()

    def test_push_correlation(self):
        app_state.push_correlation({"action": "suppress", "root_cause": "ptp_drift"})
        assert len(app_state.snapshot_correlations()) == 1

    def test_correlation_caps_at_200(self):
        for i in range(210):
            app_state.push_correlation({"action": "execute", "root_cause": f"alarm_{i}"})
        assert len(app_state.snapshot_correlations()) == 200


class TestPendingApprovals:
    def setup_method(self):
        _reset_state()

    def test_push_pending(self):
        app_state.push_pending_approval("test_alarm", "/sops/test.md", {"severity": "critical"})
        pending = app_state.snapshot_pending_approvals()
        assert "test_alarm" in pending
        assert pending["test_alarm"]["sop"] == "/sops/test.md"

    def test_pending_has_created_at(self):
        app_state.push_pending_approval("a", "/sops/a.md", {})
        assert "created_at" in app_state.snapshot_pending_approvals()["a"]


class TestActivity:
    def setup_method(self):
        _reset_state()

    def test_push_activity(self):
        app_state.push_activity("detect", "CPU overload detected", status="warning")
        activity = app_state.snapshot_activity()
        assert len(activity) == 1
        assert activity[0]["stage"] == "detect"
        assert activity[0]["status"] == "warning"

    def test_activity_caps_at_500(self):
        for i in range(510):
            app_state.push_activity("collect", f"cycle {i}")
        assert len(app_state.snapshot_activity()) == 500
