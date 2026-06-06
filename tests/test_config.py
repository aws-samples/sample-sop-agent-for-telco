# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Tests for agent/config.py — AlarmRule schema extensions (Task 1.1)."""

import yaml

from config import AlarmRule, _parse


class TestAlarmRuleSchema:
    """Tests for the extended AlarmRule dataclass and YAML parsing."""

    def test_alarm_rule_default_values(self):
        """All new fields default correctly."""
        rule = AlarmRule()
        assert rule.metric_pattern == ""
        assert rule.metrics == []
        assert rule.metric_field == ""
        assert rule.condition == ""
        assert rule.severity == "warning"
        assert rule.depends_on == []

    def test_alarm_rule_from_yaml_with_pattern(self):
        """YAML with metric_pattern parses correctly."""
        raw = yaml.safe_load("""
alarms:
  - name: smf_missing
    source: core
    metric_pattern: "smf_fivegs_*"
    condition: "absent_for 60s"
    severity: critical
""")
        config = _parse(raw)
        assert len(config.alarms) == 1
        assert config.alarms[0].metric_pattern == "smf_fivegs_*"
        assert config.alarms[0].condition == "absent_for 60s"

    def test_alarm_rule_from_yaml_with_metrics_list(self):
        """YAML with metrics: [...] parses correctly."""
        raw = yaml.safe_load("""
alarms:
  - name: compound_rule
    source: core
    metrics: [amf_health, smf_health, upf_health]
    condition: "all > 0"
    severity: warning
""")
        config = _parse(raw)
        assert len(config.alarms) == 1
        assert config.alarms[0].metrics == ["amf_health", "smf_health", "upf_health"]

    def test_alarm_rule_field_alias(self):
        """field: still aliases to metric_field (backward compat)."""
        raw = yaml.safe_load("""
alarms:
  - name: du_cpu
    source: ran
    field: du_cpu_usage_percent
    condition: "> 80"
""")
        config = _parse(raw)
        assert config.alarms[0].metric_field == "du_cpu_usage_percent"

    def test_alarm_rule_pattern_alias(self):
        """pattern: aliases to metric_pattern (NEW)."""
        raw = yaml.safe_load("""
alarms:
  - name: smf_missing
    source: core
    pattern: "smf_*"
    condition: "absent_for 60s"
""")
        config = _parse(raw)
        assert config.alarms[0].metric_pattern == "smf_*"

    def test_load_config_with_no_alarms_section(self):
        """Config with no alarms: returns empty list (legacy fallback path)."""
        raw = yaml.safe_load("""
cluster:
  name: test-cluster
  region: us-west-2
""")
        config = _parse(raw)
        assert config.alarms == []
        assert config.cluster_name == "test-cluster"
