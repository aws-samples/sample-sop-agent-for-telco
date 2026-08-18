# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Tests for 3GPP standards module."""
from amzn_cse_telco_autonomous_network_agents_app.agent.standards import (
    ALARM_TYPES,
    PROBABLE_CAUSES,
    SEVERITIES,
    build_managed_object_dn,
)


def test_alarm_types_complete():
    assert len(ALARM_TYPES) == 5
    assert "communications-alarm" in ALARM_TYPES
    assert "equipment-alarm" in ALARM_TYPES


def test_probable_causes_have_timing():
    assert "timing-problem" in PROBABLE_CAUSES
    assert PROBABLE_CAUSES["timing-problem"] == 60


def test_probable_causes_have_cpu():
    assert "cpu-cycles-limit-exceeded" in PROBABLE_CAUSES
    assert PROBABLE_CAUSES["cpu-cycles-limit-exceeded"] == 13


def test_build_dn():
    dn = build_managed_object_dn("dell-worker-2", "GNBDUFunction")
    assert dn == "SubNetwork=ANRA,ManagedElement=dell-worker-2,GNBDUFunction=1"


def test_build_dn_custom_instance():
    dn = build_managed_object_dn("node-1", "AMFFunction", "amf-01")
    assert dn == "SubNetwork=ANRA,ManagedElement=node-1,AMFFunction=amf-01"


def test_severities():
    assert "critical" in SEVERITIES
    assert "cleared" in SEVERITIES
    assert len(SEVERITIES) == 5
