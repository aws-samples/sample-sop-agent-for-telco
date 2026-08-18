# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Tests for config store wiring — verifies model_resolver reads from config_store."""

import sys
from unittest.mock import MagicMock, patch

# Mock boto3 before importing model_resolver (it imports boto3 at module level)
if "boto3" not in sys.modules:
    sys.modules["boto3"] = MagicMock()

import pytest

from amzn_cse_telco_autonomous_network_agents_app.agent.config import SiteConfig
from amzn_cse_telco_autonomous_network_agents_app.agent.core import model_resolver


class TestModelResolverConfig:
    """Verify model_resolver priority: env > config override > config tier > env tier > caller."""

    @pytest.fixture(autouse=True)
    def _clear_cache(self):
        """Clear model resolver cache before each test."""
        model_resolver.invalidate_cache()
        yield
        model_resolver.invalidate_cache()

    def test_env_override_beats_config(self, monkeypatch):
        """BEDROCK_MODEL_ID env var is returned regardless of config store values."""
        monkeypatch.setenv("BEDROCK_MODEL_ID", "us.anthropic.my-custom-model")
        cfg = SiteConfig(
            bedrock_model_override="us.anthropic.claude-sonnet-4-20250514-v1:0",
            bedrock_model_tier="smart",
        )
        with patch(
            "amzn_cse_telco_autonomous_network_agents_app.agent.core.config_store.get_config",
            return_value=cfg,
        ):
            result = model_resolver.get_model(tier="fast")
        assert result == "us.anthropic.my-custom-model"

    def test_config_override_beats_tier(self, monkeypatch):
        """config.bedrock_model_override is returned directly when set."""
        monkeypatch.delenv("BEDROCK_MODEL_ID", raising=False)
        monkeypatch.delenv("BEDROCK_MODEL_TIER", raising=False)
        cfg = SiteConfig(
            bedrock_model_override="us.anthropic.claude-sonnet-4-20250514-v1:0",
            bedrock_model_tier="fast",
        )
        with patch(
            "amzn_cse_telco_autonomous_network_agents_app.agent.core.config_store.get_config",
            return_value=cfg,
        ):
            result = model_resolver.get_model(tier="fast")
        assert result == "us.anthropic.claude-sonnet-4-20250514-v1:0"

    def test_config_tier_used_when_no_override(self, monkeypatch):
        """config.bedrock_model_tier selects the preference list (fast -> Haiku)."""
        monkeypatch.delenv("BEDROCK_MODEL_ID", raising=False)
        monkeypatch.delenv("BEDROCK_MODEL_TIER", raising=False)
        cfg = SiteConfig(bedrock_model_override="", bedrock_model_tier="fast")

        # Mock active profiles to contain the first haiku model
        haiku_model = "us.anthropic.claude-haiku-4-5-20251001-v1:0"
        with (
            patch(
                "amzn_cse_telco_autonomous_network_agents_app.agent.core.config_store.get_config",
                return_value=cfg,
            ),
            patch(
                "amzn_cse_telco_autonomous_network_agents_app.agent.core.model_resolver._list_active_profiles",
                return_value={haiku_model},
            ),
        ):
            result = model_resolver.get_model(tier="smart")  # caller says smart, config says fast
        assert result == haiku_model

    def test_config_tier_smart_selects_sonnet(self, monkeypatch):
        """config.bedrock_model_tier='smart' selects Sonnet preference list."""
        monkeypatch.delenv("BEDROCK_MODEL_ID", raising=False)
        monkeypatch.delenv("BEDROCK_MODEL_TIER", raising=False)
        cfg = SiteConfig(bedrock_model_override="", bedrock_model_tier="smart")

        sonnet_model = "us.anthropic.claude-sonnet-4-20250514-v1:0"
        with (
            patch(
                "amzn_cse_telco_autonomous_network_agents_app.agent.core.config_store.get_config",
                return_value=cfg,
            ),
            patch(
                "amzn_cse_telco_autonomous_network_agents_app.agent.core.model_resolver._list_active_profiles",
                return_value={sonnet_model},
            ),
        ):
            result = model_resolver.get_model(tier="fast")  # caller says fast, config says smart
        assert result == sonnet_model

    def test_env_tier_fallback_when_no_config(self, monkeypatch):
        """No config store available -> BEDROCK_MODEL_TIER env var is used."""
        monkeypatch.delenv("BEDROCK_MODEL_ID", raising=False)
        monkeypatch.setenv("BEDROCK_MODEL_TIER", "smart")

        sonnet_model = "us.anthropic.claude-sonnet-4-20250514-v1:0"
        # Simulate config_store not being importable by removing it from sys.modules
        # and making the import fail
        config_store_key = "amzn_cse_telco_autonomous_network_agents_app.agent.core.config_store"
        saved_module = sys.modules.get(config_store_key)
        try:
            sys.modules[config_store_key] = None  # type: ignore[assignment]  # forces ImportError on import
            with patch(
                "amzn_cse_telco_autonomous_network_agents_app.agent.core.model_resolver._list_active_profiles",
                return_value={sonnet_model},
            ):
                result = model_resolver.get_model(tier="fast")
            assert result == sonnet_model
        finally:
            if saved_module is not None:
                sys.modules[config_store_key] = saved_module
            else:
                sys.modules.pop(config_store_key, None)

    def test_env_tier_fallback_when_config_returns_none(self, monkeypatch):
        """config_store.get_config() returns None -> BEDROCK_MODEL_TIER env var is used."""
        monkeypatch.delenv("BEDROCK_MODEL_ID", raising=False)
        monkeypatch.setenv("BEDROCK_MODEL_TIER", "smart")

        sonnet_model = "us.anthropic.claude-sonnet-4-6"
        with (
            patch(
                "amzn_cse_telco_autonomous_network_agents_app.agent.core.config_store.get_config",
                return_value=None,
            ),
            patch(
                "amzn_cse_telco_autonomous_network_agents_app.agent.core.model_resolver._list_active_profiles",
                return_value={sonnet_model},
            ),
        ):
            result = model_resolver.get_model(tier="fast")
        assert result == sonnet_model

    def test_config_tier_beats_env_tier(self, monkeypatch):
        """config.bedrock_model_tier takes priority over BEDROCK_MODEL_TIER env var."""
        monkeypatch.delenv("BEDROCK_MODEL_ID", raising=False)
        monkeypatch.setenv("BEDROCK_MODEL_TIER", "smart")  # env says smart
        cfg = SiteConfig(bedrock_model_override="", bedrock_model_tier="fast")  # config says fast

        haiku_model = "us.anthropic.claude-haiku-4-5-20251001-v1:0"
        with (
            patch(
                "amzn_cse_telco_autonomous_network_agents_app.agent.core.config_store.get_config",
                return_value=cfg,
            ),
            patch(
                "amzn_cse_telco_autonomous_network_agents_app.agent.core.model_resolver._list_active_profiles",
                return_value={haiku_model},
            ),
        ):
            result = model_resolver.get_model(tier="smart")
        # Config says fast, so we should get haiku even though env says smart
        assert result == haiku_model

    def test_invalidate_cache_clears(self):
        """After invalidate_cache(), _cache is empty."""
        model_resolver._cache["fast"] = "cached-model-id"
        model_resolver._cache["_profiles"] = {"some-profile"}
        model_resolver.invalidate_cache()
        assert model_resolver._cache == {}

    def test_caller_tier_used_as_final_fallback(self, monkeypatch):
        """When no env vars and no config store, caller's tier argument is used."""
        monkeypatch.delenv("BEDROCK_MODEL_ID", raising=False)
        monkeypatch.delenv("BEDROCK_MODEL_TIER", raising=False)

        haiku_model = "us.anthropic.claude-haiku-4-5-20251001-v1:0"
        with (
            patch(
                "amzn_cse_telco_autonomous_network_agents_app.agent.core.config_store.get_config",
                return_value=None,
            ),
            patch(
                "amzn_cse_telco_autonomous_network_agents_app.agent.core.model_resolver._list_active_profiles",
                return_value={haiku_model},
            ),
        ):
            result = model_resolver.get_model(tier="fast")
        assert result == haiku_model


class TestApprovalModeLive:
    """Test that approval_mode can be read from config store."""

    def test_approval_mode_from_config(self):
        """get_config().approval_mode returns the config value."""
        cfg = SiteConfig(approval_mode="manual")
        with patch(
            "amzn_cse_telco_autonomous_network_agents_app.agent.core.config_store.get_config",
            return_value=cfg,
        ):
            from amzn_cse_telco_autonomous_network_agents_app.agent.core.config_store import (
                get_config,
            )

            result = get_config()
            assert result.approval_mode == "manual"

    def test_approval_mode_default_is_auto(self):
        """Default SiteConfig.approval_mode is 'auto'."""
        cfg = SiteConfig()
        assert cfg.approval_mode == "auto"
