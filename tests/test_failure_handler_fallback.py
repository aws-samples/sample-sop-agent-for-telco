# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
"""Tests for failure_handler.py — Tier 1 deterministic fallback."""

from unittest.mock import MagicMock, patch

from amzn_cse_telco_autonomous_network_agents_app.agent.agents.anpa.failure_handler import (
    _classify_failure,
    try_deterministic_fallback,
)


class TestClassifyFailure:
    def test_extracts_known_type_from_error(self):
        assert (
            _classify_failure(
                "BMC pre-configuration failed: VIRTUAL_MEDIA_MOUNT_FAILED"
            )
            == "VIRTUAL_MEDIA_MOUNT_FAILED"
        )

    def test_extracts_dell_oem_failure(self):
        assert (
            _classify_failure("step failed: DELL_OEM_BOOT_FAILED (HTTP 400)")
            == "DELL_OEM_BOOT_FAILED"
        )

    def test_infers_virtual_media_from_message(self):
        assert (
            _classify_failure("VirtualMedia InsertMedia failed (HTTP 500)")
            == "VIRTUAL_MEDIA_MOUNT_FAILED"
        )

    def test_infers_boot_override_from_message(self):
        assert (
            _classify_failure("BootSourceOverride PATCH failed")
            == "BOOT_OVERRIDE_FAILED"
        )

    def test_returns_empty_for_unknown(self):
        assert _classify_failure("some random error nobody knows") == ""


class TestTryDeterministicFallback:
    @patch(
        "amzn_cse_telco_autonomous_network_agents_app.agent.agents.anpa.failure_handler._get_current_strategy"
    )
    def test_returns_false_if_no_strategy_annotation(self, mock_get_strat):
        mock_get_strat.return_value = ""
        result = try_deterministic_fallback("req-1", "ns", {}, "some error")
        assert result is False

    @patch(
        "amzn_cse_telco_autonomous_network_agents_app.agent.agents.anpa.failure_handler._get_current_strategy"
    )
    def test_returns_false_if_unknown_failure(self, mock_get_strat):
        mock_get_strat.return_value = "primary"
        result = try_deterministic_fallback("req-1", "ns", {}, "disk full")
        assert result is False

    @patch("amzn_cse_telco_autonomous_network_agents_app.agent.core.executor.run_cmd")
    @patch(
        "amzn_cse_telco_autonomous_network_agents_app.agent.agents.anpa.failure_handler._load_cached_profile"
    )
    @patch(
        "amzn_cse_telco_autonomous_network_agents_app.agent.agents.anpa.failure_handler._get_current_strategy"
    )
    def test_returns_false_if_no_cached_profile(
        self, mock_get_strat, mock_load, mock_cmd
    ):
        mock_get_strat.return_value = "primary"
        mock_load.return_value = (None, {})
        result = try_deterministic_fallback(
            "req-1", "ns", {}, "VIRTUAL_MEDIA_MOUNT_FAILED"
        )
        assert result is False

    @patch("amzn_cse_telco_autonomous_network_agents_app.agent.core.executor.run_cmd")
    @patch(
        "amzn_cse_telco_autonomous_network_agents_app.agent.agents.anpa.failure_handler._record_outcome"
    )
    @patch(
        "amzn_cse_telco_autonomous_network_agents_app.agent.agents.anpa.boot_configurer.BootConfigurer"
    )
    @patch("amzn_cse_telco_autonomous_network_agents_app.agent.config.load_config")
    @patch(
        "amzn_cse_telco_autonomous_network_agents_app.agent.agents.anpa.strategy_engine.StrategyEngine"
    )
    @patch(
        "amzn_cse_telco_autonomous_network_agents_app.agent.agents.anpa.failure_handler._load_cached_profile"
    )
    @patch(
        "amzn_cse_telco_autonomous_network_agents_app.agent.agents.anpa.failure_handler._get_current_strategy"
    )
    def test_successful_fallback(
        self,
        mock_get_strat,
        mock_load,
        mock_engine_cls,
        mock_config,
        mock_bc_cls,
        mock_record,
        mock_cmd,
    ):
        mock_get_strat.return_value = "primary"
        mock_profile = MagicMock()
        mock_load.return_value = (mock_profile, {"strategies": []})

        mock_engine = MagicMock()
        mock_fallback = MagicMock()
        mock_fallback.name = "fallback_rfs"
        mock_engine.get_fallback_for_failure.return_value = mock_fallback
        mock_engine_cls.return_value = mock_engine

        mock_config.return_value = MagicMock(hookos_iso_url="http://proxy/hook.iso")

        mock_boot_result = MagicMock()
        mock_boot_result.success = True
        mock_configurer = MagicMock()
        mock_configurer.execute.return_value = mock_boot_result
        mock_bc_cls.return_value = mock_configurer

        mock_cmd_result = MagicMock()
        mock_cmd_result.success = True
        mock_cmd.return_value = mock_cmd_result

        spec = {"nodes": [{"hostname": "worker-01", "bmcAddress": "10.0.0.1"}]}
        result = try_deterministic_fallback(
            "req-1", "ns", spec, "VIRTUAL_MEDIA_MOUNT_FAILED"
        )

        assert result is True
        mock_configurer.execute.assert_called_once_with(mock_fallback)
        mock_record.assert_called_once()

    @patch("amzn_cse_telco_autonomous_network_agents_app.agent.core.executor.run_cmd")
    @patch(
        "amzn_cse_telco_autonomous_network_agents_app.agent.agents.anpa.boot_configurer.BootConfigurer"
    )
    @patch("amzn_cse_telco_autonomous_network_agents_app.agent.config.load_config")
    @patch(
        "amzn_cse_telco_autonomous_network_agents_app.agent.agents.anpa.strategy_engine.StrategyEngine"
    )
    @patch(
        "amzn_cse_telco_autonomous_network_agents_app.agent.agents.anpa.failure_handler._load_cached_profile"
    )
    @patch(
        "amzn_cse_telco_autonomous_network_agents_app.agent.agents.anpa.failure_handler._get_current_strategy"
    )
    def test_fallback_execution_fails_returns_false(
        self,
        mock_get_strat,
        mock_load,
        mock_engine_cls,
        mock_config,
        mock_bc_cls,
        mock_cmd,
    ):
        mock_get_strat.return_value = "primary"
        mock_profile = MagicMock()
        mock_load.return_value = (mock_profile, {"strategies": []})

        mock_engine = MagicMock()
        mock_fallback = MagicMock()
        mock_fallback.name = "fallback_rfs"
        mock_engine.get_fallback_for_failure.return_value = mock_fallback
        mock_engine_cls.return_value = mock_engine

        mock_config.return_value = MagicMock(hookos_iso_url="http://proxy/hook.iso")

        mock_boot_result = MagicMock()
        mock_boot_result.success = False
        mock_boot_result.failure_step = "configure_rfs"
        mock_boot_result.failure_reason = "RFS not available"
        mock_configurer = MagicMock()
        mock_configurer.execute.return_value = mock_boot_result
        mock_bc_cls.return_value = mock_configurer

        spec = {"nodes": [{"hostname": "worker-01", "bmcAddress": "10.0.0.1"}]}
        result = try_deterministic_fallback(
            "req-1", "ns", spec, "VIRTUAL_MEDIA_MOUNT_FAILED"
        )

        assert result is False

    @patch(
        "amzn_cse_telco_autonomous_network_agents_app.agent.agents.anpa.strategy_engine.StrategyEngine"
    )
    @patch(
        "amzn_cse_telco_autonomous_network_agents_app.agent.agents.anpa.failure_handler._load_cached_profile"
    )
    @patch(
        "amzn_cse_telco_autonomous_network_agents_app.agent.agents.anpa.failure_handler._get_current_strategy"
    )
    def test_no_fallback_available_returns_false(
        self, mock_get_strat, mock_load, mock_engine_cls
    ):
        mock_get_strat.return_value = "fallback_rfs"
        mock_profile = MagicMock()
        mock_load.return_value = (mock_profile, {"strategies": []})

        mock_engine = MagicMock()
        mock_engine.get_fallback_for_failure.return_value = None
        mock_engine_cls.return_value = mock_engine

        result = try_deterministic_fallback("req-1", "ns", {}, "DELL_OEM_BOOT_FAILED")

        assert result is False
