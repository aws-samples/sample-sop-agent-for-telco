# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Tests for app_state (workshop branch equivalent of execution_state)."""

import pytest
from app_state import (
    _active_alarm_names,
    _alarms,
    _executions,
    push_alarm,
)


def test_push_alarm():
    _alarms.clear()
    _active_alarm_names.clear()
    push_alarm({"name": "test_alarm", "severity": "critical"})
    assert "test_alarm" in _active_alarm_names
    assert len(_alarms) == 1


def test_push_alarm_deduplicates():
    _alarms.clear()
    _active_alarm_names.clear()
    push_alarm({"name": "dup_alarm", "severity": "critical"})
    push_alarm({"name": "dup_alarm", "severity": "critical"})
    assert len([a for a in _alarms if a["name"] == "dup_alarm"]) == 1
