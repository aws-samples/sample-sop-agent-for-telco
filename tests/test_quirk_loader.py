# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
"""Tests for quirks/loader.py — vendor quirk matching."""

from unittest.mock import MagicMock

import pytest

from amzn_cse_telco_autonomous_network_agents_app.agent.agents.anpa.quirks.loader import (
    invalidate_cache,
    match,
)


@pytest.fixture(autouse=True)
def _clear_cache():
    invalidate_cache()
    yield
    invalidate_cache()


def _make_profile(**kwargs):
    p = MagicMock()
    p.model = kwargs.get("model", "Unknown")
    p.firmware_version = kwargs.get("firmware_version", "1.0")
    return p


class TestQuirkMatch:
    def test_dell_xr8720t_matches(self):
        profile = _make_profile(model="PowerEdge XR8720t", firmware_version="7.10.30.00")
        quirk = match(profile)
        assert "xr8720t" in quirk.get("_source", "").lower()
        assert quirk["boot"]["boot_source_override_writable"] is False

    def test_unknown_model_returns_default(self):
        profile = _make_profile(model="SuperServer 9999X")
        quirk = match(profile)
        assert quirk["_source"] == "_default.yaml"

    def test_dell_xr8720t_has_strategies(self):
        profile = _make_profile(model="PowerEdge XR8720t")
        quirk = match(profile)
        strategies = quirk.get("strategies", [])
        assert len(strategies) >= 2
        assert strategies[0]["name"] == "primary"
        assert strategies[0]["mount_method"] == "virtual_media_cd"

    def test_default_has_standard_strategy(self):
        profile = _make_profile(model="Generic BMC")
        quirk = match(profile)
        strategies = quirk.get("strategies", [])
        assert len(strategies) >= 1
        assert strategies[0]["boot_method"] == "standard_redfish_boot_override"

    def test_caching_works(self):
        profile = _make_profile(model="PowerEdge XR8720t")
        q1 = match(profile)
        q2 = match(profile)
        assert q1 is q2  # same object from cache

    def test_case_insensitive_match(self):
        profile = _make_profile(model="POWEREDGE xr8720T")
        quirk = match(profile)
        assert "xr8720t" in quirk.get("_source", "").lower()
