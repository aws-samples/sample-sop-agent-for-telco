# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Tests for core/context.py — standardized context schemas."""
import time


from amzn_cse_telco_autonomous_network_agents_app.agent.core.context import AlarmContext, CorrelationResult, ExecutionResult, RemediationPlan, VerificationResult


class TestAlarmContext:
    def test_create_minimal(self):
        a = AlarmContext(name="test", severity="critical", source="influxdb")
        assert a.name == "test"
        assert a.layer == -1

    def test_to_dict_excludes_empty(self):
        a = AlarmContext(name="test", severity="critical", source="influxdb")
        d = a.to_dict()
        assert "name" in d
        assert "vendor_description" not in d  # empty string excluded

    def test_to_dict_keeps_value_zero(self):
        a = AlarmContext(name="test", severity="warning", source="influxdb", value=0)
        d = a.to_dict()
        assert "value" in d

    def test_to_dict_keeps_layer(self):
        a = AlarmContext(name="test", severity="warning", source="influxdb", layer=-1)
        d = a.to_dict()
        assert "layer" in d

    def test_from_dict(self):
        d = {"name": "cpu_high", "severity": "critical", "source": "influxdb", "value": 85.0, "layer": 3}
        a = AlarmContext.from_dict(d)
        assert a.name == "cpu_high"
        assert a.value == 85.0
        assert a.layer == 3

    def test_from_dict_ignores_unknown(self):
        d = {"name": "x", "severity": "warning", "source": "test", "unknown_field": "ignored"}
        a = AlarmContext.from_dict(d)
        assert a.name == "x"

    def test_timestamp_auto_set(self):
        before = time.time()
        a = AlarmContext(name="x", severity="warning", source="test")
        assert a.timestamp >= before


class TestCorrelationResult:
    def test_create(self):
        c = CorrelationResult(action="suppress", root_cause="ptp_drift", symptoms=["du_timing"])
        assert c.action == "suppress"
        assert c.confidence == "high"

    def test_to_dict(self):
        c = CorrelationResult(action="execute", root_cause="cpu_overload")
        d = c.to_dict()
        assert d["action"] == "execute"
        assert "timestamp" in d

    def test_from_dict(self):
        d = {"action": "escalate", "root_cause": "unknown", "confidence": "low"}
        c = CorrelationResult.from_dict(d)
        assert c.action == "escalate"
        assert c.confidence == "low"


class TestRemediationPlan:
    def test_create(self):
        p = RemediationPlan(alarm_name="test", sop_path="/sops/test.md")
        assert p.generated is False

    def test_to_dict_with_correlation(self):
        corr = CorrelationResult(action="execute", root_cause="test")
        p = RemediationPlan(alarm_name="test", sop_path="/sops/x.md", correlation=corr)
        d = p.to_dict()
        assert d["correlation"]["action"] == "execute"


class TestExecutionResult:
    def test_to_dict_excludes_empty(self):
        r = ExecutionResult(status="completed", duration_seconds=5.2)
        d = r.to_dict()
        assert "status" in d
        assert "error" not in d  # empty string excluded

    def test_error_included_when_set(self):
        r = ExecutionResult(status="error", error="timeout")
        d = r.to_dict()
        assert d["error"] == "timeout"


class TestVerificationResult:
    def test_create(self):
        v = VerificationResult(status="pass", soak_time_seconds=60)
        assert v.recommendation == ""

    def test_to_dict(self):
        v = VerificationResult(status="fail", recommendation="rollback", new_issues=["new_alarm"])
        d = v.to_dict()
        assert d["new_issues"] == ["new_alarm"]
