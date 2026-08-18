# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
"""Tests for strategy_engine.py — provisioning strategy selection."""

from unittest.mock import MagicMock

from amzn_cse_telco_autonomous_network_agents_app.agent.agents.anpa.strategy_engine import (
    StrategyEngine,
)


def _make_profile(**kwargs):
    p = MagicMock()
    p.boot_override_writable = kwargs.get("boot_override_writable", True)
    p.oem_namespace = kwargs.get("oem_namespace", "")
    p.requires_custom_hookos = kwargs.get("requires_custom_hookos", False)
    p.model = kwargs.get("model", "Generic")
    return p


DELL_QUIRKS = {
    "strategies": [
        {
            "name": "primary",
            "description": "VirtualMedia CD + Dell OEM boot",
            "mount_method": "virtual_media_cd",
            "boot_method": "dell_oem_first_boot_device",
            "hookos_variant": "patched-ice",
            "pre_steps": [{"action": "set_dell_oem_boot", "params": {"device": "VCD-DVD"}}],
            "post_steps": [],
            "fallback_name": "fallback_rfs",
        },
        {
            "name": "fallback_rfs",
            "description": "Dell RFS network file",
            "mount_method": "rfs_network_file",
            "boot_method": "dell_oem_first_boot_device",
            "hookos_variant": "patched-ice",
            "pre_steps": [{"action": "configure_rfs", "params": {"enable": True}}],
            "post_steps": [],
            "fallback_name": None,
        },
    ]
}

DEFAULT_QUIRKS = {
    "strategies": [
        {
            "name": "default",
            "description": "Standard Redfish",
            "mount_method": "virtual_media_cd",
            "boot_method": "standard_redfish_boot_override",
            "hookos_variant": "standard",
            "pre_steps": [],
            "post_steps": [],
            "fallback_name": None,
        }
    ]
}


class TestStrategySelection:
    def test_quirk_strategies_used_first(self):
        engine = StrategyEngine()
        profile = _make_profile(boot_override_writable=False, oem_namespace="Dell")
        strategy = engine.select(profile, DELL_QUIRKS)
        assert strategy.name == "primary"
        assert strategy.boot_method == "dell_oem_first_boot_device"
        assert strategy.hookos_variant == "patched-ice"

    def test_default_quirk_selects_standard(self):
        engine = StrategyEngine()
        profile = _make_profile()
        strategy = engine.select(profile, DEFAULT_QUIRKS)
        assert strategy.name == "default"
        assert strategy.boot_method == "standard_redfish_boot_override"

    def test_inferred_dell_oem_when_no_quirk_strategies(self):
        engine = StrategyEngine()
        profile = _make_profile(boot_override_writable=False, oem_namespace="Dell")
        strategy = engine.select(profile, {"strategies": []})
        assert strategy.name == "inferred_dell_oem"
        assert strategy.boot_method == "dell_oem_first_boot_device"

    def test_default_strategy_when_standard_bmc(self):
        engine = StrategyEngine()
        profile = _make_profile(boot_override_writable=True)
        strategy = engine.select(profile, {"strategies": []})
        assert strategy.name == "default"

    def test_custom_hookos_propagated(self):
        engine = StrategyEngine()
        profile = _make_profile(boot_override_writable=True, requires_custom_hookos=True)
        strategy = engine.select(profile, {"strategies": []})
        assert strategy.hookos_variant == "patched-ice"

    def test_pre_steps_from_quirk(self):
        engine = StrategyEngine()
        profile = _make_profile()
        strategy = engine.select(profile, DELL_QUIRKS)
        assert len(strategy.pre_steps) >= 1
        assert strategy.pre_steps[0]["action"] == "set_dell_oem_boot"


class TestFallbackChain:
    def test_fallback_for_virtual_media_failure(self):
        engine = StrategyEngine()
        fallback = engine.get_fallback_for_failure("primary", "VIRTUAL_MEDIA_MOUNT_FAILED", DELL_QUIRKS)
        assert fallback is not None
        assert fallback.name == "fallback_rfs"
        assert fallback.mount_method == "rfs_network_file"

    def test_no_fallback_from_last_strategy(self):
        engine = StrategyEngine()
        fallback = engine.get_fallback_for_failure("fallback_rfs", "SOME_FAILURE", DELL_QUIRKS)
        assert fallback is None

    def test_unknown_strategy_returns_none(self):
        engine = StrategyEngine()
        fallback = engine.get_fallback_for_failure("nonexistent", "SOME_FAILURE", DELL_QUIRKS)
        assert fallback is None

    def test_default_strategy_has_no_fallback(self):
        engine = StrategyEngine()
        fallback = engine.get_fallback_for_failure("default", "SOME_FAILURE", DEFAULT_QUIRKS)
        assert fallback is None
