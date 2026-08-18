# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Tests for the ANRA cloudwatch_events module.

Covers the kubectl fallback path (poll_k8s_pod_health) and the CloudWatch
poll's rate-limit gate. These functions had no coverage before the monitor.py
decomposition moved them here.
"""

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from amzn_cse_telco_autonomous_network_agents_app.agent.agents.anra.monitoring import (
    cloudwatch_events,
)


@pytest.fixture(autouse=True)
def _isolate_module_state():
    """Snapshot and restore the module's dedup/rate-limit globals around each test.

    poll_cloudwatch_k8s_events mutates module-level _cw_last_poll and _cw_seen;
    tests set them to force a code path. Save/restore here so no test's mutation
    leaks into another regardless of run order.
    """
    saved_last_poll = cloudwatch_events._cw_last_poll
    saved_seen = dict(cloudwatch_events._cw_seen)
    try:
        yield
    finally:
        cloudwatch_events._cw_last_poll = saved_last_poll
        cloudwatch_events._cw_seen.clear()
        cloudwatch_events._cw_seen.update(saved_seen)


def _r(stdout="", returncode=0):
    return SimpleNamespace(stdout=stdout, returncode=returncode, success=returncode == 0)


class TestPollK8sPodHealth:
    def _cfg(self):
        return SimpleNamespace(nodes=[SimpleNamespace(namespaces=["srsran"])])

    @patch("amzn_cse_telco_autonomous_network_agents_app.agent.config.load_config")
    def test_crashloop_pod_becomes_critical_alert(self, mock_cfg):
        mock_cfg.return_value = self._cfg()
        row = "amf-0 Running 5 CrashLoopBackOff"
        with patch(
            "amzn_cse_telco_autonomous_network_agents_app.agent.core.executor.run_cmd",
            return_value=_r(stdout=row),
        ):
            alerts = cloudwatch_events.poll_k8s_pod_health()
        assert len(alerts) == 1
        assert alerts[0]["name"] == "nf_crashloop"
        assert alerts[0]["severity"] == "critical"
        assert alerts[0]["source"] == "k8s-pod-health"
        assert alerts[0]["value"] == 5

    @patch("amzn_cse_telco_autonomous_network_agents_app.agent.config.load_config")
    def test_healthy_pod_yields_no_alert(self, mock_cfg):
        mock_cfg.return_value = self._cfg()
        # Running pod with a benign waiting reason (<none>) -> no alert.
        row = "upf-0 Running 0 <none>"
        with patch(
            "amzn_cse_telco_autonomous_network_agents_app.agent.core.executor.run_cmd",
            return_value=_r(stdout=row),
        ):
            alerts = cloudwatch_events.poll_k8s_pod_health()
        assert alerts == []

    @patch("amzn_cse_telco_autonomous_network_agents_app.agent.config.load_config")
    def test_kubectl_failure_returns_empty(self, mock_cfg):
        mock_cfg.return_value = self._cfg()
        with patch(
            "amzn_cse_telco_autonomous_network_agents_app.agent.core.executor.run_cmd",
            return_value=_r(returncode=1),
        ):
            assert cloudwatch_events.poll_k8s_pod_health() == []


class TestCloudwatchRateLimit:
    def test_poll_is_rate_limited(self, monkeypatch):
        # A call at the same clock as the last poll is inside the 60s window, so
        # it must short-circuit before ever building a session.
        monkeypatch.setattr(cloudwatch_events.time, "time", lambda: 1000.0)
        cloudwatch_events._cw_last_poll = 1000.0

        def _boom(*_a, **_kw):
            raise AssertionError("should not build a session inside the rate-limit window")

        with patch.object(cloudwatch_events, "aws_session", _boom):
            assert cloudwatch_events.poll_cloudwatch_k8s_events() == []


class TestCloudwatchQueryPath:
    """Exercise the CloudWatch query loop, incl. the ResourceNotFoundException
    skip that made monitor's copy canonical over the deleted twin."""

    def _cfg(self):
        return SimpleNamespace(
            bedrock_profile="",
            cluster_region="us-west-1",
            cluster_name="c1",
            nodes=[SimpleNamespace(namespaces=["srsran"])],
        )

    def _hit_row(self, message="Container killed due to OOMKilled"):
        # One matching row in the watched namespace.
        return {
            "results": [
                [
                    {"field": "ns", "value": "srsran"},
                    {"field": "pod", "value": "amf-0"},
                    {"field": "message", "value": message},
                ]
            ],
            "status": "Complete",
        }

    def _fake_session_returning(self, hit):
        class _FakeLogs:
            def start_query(self, **_kw):
                return {"queryId": "q1"}

            def get_query_results(self, **_kw):
                return hit

        return SimpleNamespace(client=lambda _name: _FakeLogs())

    def test_missing_log_group_is_skipped_not_fatal(self, monkeypatch):
        # First log group raises ResourceNotFoundException; second returns a hit.
        # The alert from the second group must still come through -- i.e. a
        # missing log group is skipped, not fatal. This is the exact behavior
        # the deleted twin lacked.
        monkeypatch.setattr(cloudwatch_events.time, "time", lambda: 5000.0)
        monkeypatch.setattr(cloudwatch_events.time, "sleep", lambda _s: None)
        cloudwatch_events._cw_last_poll = 0.0
        cloudwatch_events._cw_seen.clear()

        class _RNF(Exception):
            pass

        hit = self._hit_row()

        class _FakeLogs:
            exceptions = SimpleNamespace(ResourceNotFoundException=_RNF)

            def __init__(self):
                self._calls = 0

            def start_query(self, **_kw):
                self._calls += 1
                if self._calls == 1:
                    raise _RNF("no such log group")
                return {"queryId": "q1"}

            def get_query_results(self, **_kw):
                return hit

        fake_session = SimpleNamespace(client=lambda _name: _FakeLogs())

        with (
            patch("amzn_cse_telco_autonomous_network_agents_app.agent.config.load_config", return_value=self._cfg()),
            patch.object(cloudwatch_events, "aws_session", lambda *_a, **_kw: fake_session),
        ):
            alerts = cloudwatch_events.poll_cloudwatch_k8s_events()

        assert len(alerts) == 1
        assert alerts[0]["source"] == "cloudwatch-k8s"
        assert alerts[0]["name"] == "k8s_oomkilled"
        assert alerts[0]["severity"] == "critical"  # OOMKilled

    def test_crashloopbackoff_matches_before_backoff(self, monkeypatch):
        # A "CrashLoopBackOff" message must classify as CrashLoopBackOff
        # (critical), not the substring "BackOff" (warning). CW_ALARM_REASONS is
        # an ordered tuple with the more-specific token first, so the match is
        # deterministic -- guards against reverting it to a set.
        monkeypatch.setattr(cloudwatch_events.time, "time", lambda: 6000.0)
        monkeypatch.setattr(cloudwatch_events.time, "sleep", lambda _s: None)
        cloudwatch_events._cw_last_poll = 0.0
        cloudwatch_events._cw_seen.clear()

        hit = self._hit_row(message="Back-off restarting failed container: CrashLoopBackOff")
        fake_session = self._fake_session_returning(hit)

        with (
            patch("amzn_cse_telco_autonomous_network_agents_app.agent.config.load_config", return_value=self._cfg()),
            patch.object(cloudwatch_events, "aws_session", lambda *_a, **_kw: fake_session),
        ):
            alerts = cloudwatch_events.poll_cloudwatch_k8s_events()

        assert len(alerts) == 1
        assert alerts[0]["name"] == "k8s_crashloopbackoff"
        assert alerts[0]["severity"] == "critical"
