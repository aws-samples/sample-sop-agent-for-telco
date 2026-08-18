# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Tests for standards.py — auto-classification of alarms."""


from amzn_cse_telco_autonomous_network_agents_app.agent.standards import classify_alarm


class TestClassifyAlarm:
    def test_crashloop(self):
        r = classify_alarm("k8s_crashloopbackoff")
        assert r["alarmType"] == "processing-error-alarm"
        assert r["probableCauseCode"] == 54  # software-error

    def test_oomkilled(self):
        r = classify_alarm("k8s_oomkilled")
        assert r["alarmType"] == "processing-error-alarm"
        assert r["probableCauseCode"] == 39  # out-of-memory

    def test_thermal(self):
        r = classify_alarm("hw_thermal_warning")
        assert r["alarmType"] == "environmental-alarm"
        assert r["probableCauseCode"] == 58

    def test_power(self):
        r = classify_alarm("hw_power_failure")
        assert r["alarmType"] == "equipment-alarm"
        assert r["probableCauseCode"] == 44

    def test_transport_link(self):
        r = classify_alarm("transport_link_down")
        assert r["alarmType"] == "communications-alarm"

    def test_unknown_defaults_to_threshold(self):
        r = classify_alarm("completely_unknown_alarm_xyz")
        assert r["alarmType"] == "quality-of-service-alarm"
        assert r["probableCauseCode"] == 59  # threshold-crossed
        assert r["perceivedSeverity"] == "warning"

    def test_case_insensitive(self):
        r = classify_alarm("K8S_CrashLoopBackOff")
        assert r["alarmType"] == "processing-error-alarm"

    def test_failed_scheduling(self):
        r = classify_alarm("k8s_failedscheduling")
        assert r["probableCauseCode"] == 51
