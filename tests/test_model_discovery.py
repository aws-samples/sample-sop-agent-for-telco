# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Unit tests for model_discovery module."""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import ClientError

sys.path.insert(0, str(Path(__file__).parent.parent / "sop-agent"))

from model_discovery import (
    _CANDIDATE_MODELS,
    _LEGACY_KEY_TO_TIER,
    DiscoveredModels,
    _cache,
    _probe_model,
    discover_models,
    get_model_id,
    resolve_model_key,
)


@pytest.fixture(autouse=True)
def clear_cache():
    """Clear the module-level cache before each test."""
    _cache.clear()
    yield
    _cache.clear()


@pytest.fixture
def mock_session():
    """Create a mock boto3 session."""
    session = MagicMock()
    session.region_name = "us-west-2"
    return session


@pytest.fixture
def mock_client():
    """Create a mock bedrock-runtime client with proper exception classes."""
    client = MagicMock()
    # Create real exception classes that inherit from BaseException
    client.exceptions.ValidationException = type("ValidationException", (ClientError,), {})
    client.exceptions.AccessDeniedException = type("AccessDeniedException", (ClientError,), {})
    return client


def _make_client_with_exceptions():
    """Create a mock client whose exceptions are catchable in except clauses."""
    client = MagicMock()
    client.exceptions = MagicMock()
    client.exceptions.ValidationException = type("ValidationException", (ClientError,), {})
    client.exceptions.AccessDeniedException = type("AccessDeniedException", (ClientError,), {})
    return client


class TestProbeModel:
    """Tests for _probe_model (uses invoke_model API)."""

    def test_returns_true_on_success(self, mock_client):
        mock_client.invoke_model.return_value = {"body": MagicMock()}
        assert _probe_model(mock_client, "us.anthropic.claude-sonnet-4-6") is True

    def test_returns_false_on_resource_not_found(self, mock_client):
        error = ClientError(
            {"Error": {"Code": "ResourceNotFoundException", "Message": "use case details"}}, "InvokeModel"
        )
        error.__class__.__name__ = "ResourceNotFoundException"
        mock_client.invoke_model.side_effect = error
        assert _probe_model(mock_client, "us.anthropic.claude-sonnet-4-6") is False

    def test_returns_false_on_validation_exception(self, mock_client):
        error = mock_client.exceptions.ValidationException(
            {"Error": {"Code": "ValidationException", "Message": "use inference profile"}}, "InvokeModel"
        )
        mock_client.invoke_model.side_effect = error
        assert _probe_model(mock_client, "some-model") is False

    def test_returns_false_on_access_denied(self, mock_client):
        error = mock_client.exceptions.AccessDeniedException(
            {"Error": {"Code": "AccessDeniedException", "Message": "denied"}}, "InvokeModel"
        )
        mock_client.invoke_model.side_effect = error
        assert _probe_model(mock_client, "some-model") is False

    def test_returns_true_on_throttling(self, mock_client):
        error = ClientError({"Error": {"Code": "ThrottlingException", "Message": "rate exceeded"}}, "InvokeModel")
        error.__class__.__name__ = "ThrottlingException"
        mock_client.invoke_model.side_effect = error
        assert _probe_model(mock_client, "us.anthropic.claude-sonnet-4-6") is True

    def test_returns_false_on_legacy_marker(self, mock_client):
        error = Exception("Legacy model - not available")
        mock_client.invoke_model.side_effect = error
        assert _probe_model(mock_client, "old-model") is False

    def test_returns_false_on_use_case_in_message(self, mock_client):
        error = Exception("Model use case details have not been submitted")
        mock_client.invoke_model.side_effect = error
        assert _probe_model(mock_client, "some-model") is False

    def test_sends_minimal_invoke_model_request(self, mock_client):
        mock_client.invoke_model.return_value = {"body": MagicMock()}
        _probe_model(mock_client, "test-model")
        mock_client.invoke_model.assert_called_once()
        call_kwargs = mock_client.invoke_model.call_args[1]
        assert call_kwargs["modelId"] == "test-model"
        assert call_kwargs["contentType"] == "application/json"
        assert call_kwargs["accept"] == "application/json"
        assert "anthropic_version" in call_kwargs["body"]


class TestDiscoverModels:
    """Tests for discover_models."""

    def test_discovers_all_three_tiers(self, mock_session):
        client = MagicMock()
        client.exceptions = MagicMock()
        client.invoke_model.return_value = {"body": MagicMock()}
        mock_session.client.return_value = client

        result = discover_models(boto_session=mock_session, region="us-west-2")

        assert result.fast is not None
        assert result.balanced is not None
        assert result.powerful is not None
        assert result.region == "us-west-2"
        assert result.discovery_time_ms >= 0

    def test_stops_probing_tier_after_first_success(self, mock_session):
        client = MagicMock()
        client.exceptions = MagicMock()
        # All succeed
        client.invoke_model.return_value = {"body": MagicMock()}
        mock_session.client.return_value = client

        result = discover_models(boto_session=mock_session, region="us-west-2")

        # Should find exactly 3 (one per tier) since it stops early
        assert len(result.all_available) == 3

    @patch("model_discovery._probe_model", return_value=False)
    def test_handles_no_models_available(self, mock_probe, mock_session):
        mock_session.client.return_value = MagicMock()

        result = discover_models(boto_session=mock_session, region="us-west-2")

        assert result.fast is None
        assert result.balanced is None
        assert result.powerful is None
        assert len(result.all_available) == 0

    def test_partial_availability(self, mock_session):
        """Only balanced tier available — fast and powerful fail."""

        def selective_probe(client, model_id):
            return "sonnet" in model_id

        mock_session.client.return_value = MagicMock()
        with patch("model_discovery._probe_model", side_effect=selective_probe):
            result = discover_models(boto_session=mock_session, region="us-west-2")

        assert result.balanced is not None
        assert "sonnet" in result.balanced
        assert result.powerful is None
        assert result.fast is None

    def test_caches_results_per_region(self, mock_session):
        client = MagicMock()
        client.exceptions = MagicMock()
        client.converse.return_value = {"output": {}}
        mock_session.client.return_value = client

        result1 = discover_models(boto_session=mock_session, region="us-west-2")
        result2 = discover_models(boto_session=mock_session, region="us-west-2")

        assert result1 is result2
        # Client should only be created once
        assert mock_session.client.call_count == 1

    def test_force_bypasses_cache(self, mock_session):
        client = MagicMock()
        client.exceptions = MagicMock()
        client.converse.return_value = {"output": {}}
        mock_session.client.return_value = client

        discover_models(boto_session=mock_session, region="us-west-2")
        discover_models(boto_session=mock_session, region="us-west-2", force=True)

        assert mock_session.client.call_count == 2

    def test_different_regions_cached_separately(self, mock_session):
        client = MagicMock()
        client.exceptions = MagicMock()
        client.converse.return_value = {"output": {}}
        mock_session.client.return_value = client

        r1 = discover_models(boto_session=mock_session, region="us-west-2")
        mock_session.region_name = "us-east-1"
        r2 = discover_models(boto_session=mock_session, region="us-east-1")

        assert r1.region == "us-west-2"
        assert r2.region == "us-east-1"


class TestDiscoveredModels:
    """Tests for DiscoveredModels dataclass."""

    def test_get_returns_exact_tier(self):
        m = DiscoveredModels(fast="haiku", balanced="sonnet", powerful="opus")
        assert m.get("fast") == "haiku"
        assert m.get("balanced") == "sonnet"
        assert m.get("powerful") == "opus"

    def test_get_fallback_powerful_to_balanced(self):
        m = DiscoveredModels(balanced="sonnet")
        assert m.get("powerful") == "sonnet"

    def test_get_fallback_powerful_to_fast(self):
        m = DiscoveredModels(fast="haiku")
        assert m.get("powerful") == "haiku"

    def test_get_fallback_balanced_to_powerful(self):
        m = DiscoveredModels(powerful="opus")
        assert m.get("balanced") == "opus"

    def test_get_fallback_fast_to_balanced(self):
        m = DiscoveredModels(balanced="sonnet")
        assert m.get("fast") == "sonnet"

    def test_get_returns_none_when_empty(self):
        m = DiscoveredModels()
        assert m.get("fast") is None
        assert m.get("balanced") is None
        assert m.get("powerful") is None

    def test_summary_shows_available_models(self):
        m = DiscoveredModels(
            fast="haiku-id",
            fast_name="Haiku 4.5",
            balanced="sonnet-id",
            balanced_name="Sonnet 4.6",
            region="us-west-2",
            discovery_time_ms=1234,
        )
        summary = m.summary()
        assert "Haiku 4.5" in summary
        assert "Sonnet 4.6" in summary
        assert "1234ms" in summary

    def test_summary_shows_warning_when_empty(self):
        m = DiscoveredModels(region="us-west-2", discovery_time_ms=500)
        assert "No models available" in m.summary()


class TestGetModelId:
    """Tests for get_model_id."""

    def test_returns_model_for_valid_tier(self, mock_session):
        client = MagicMock()
        client.exceptions = MagicMock()
        client.converse.return_value = {"output": {}}
        mock_session.client.return_value = client

        model_id = get_model_id("balanced", boto_session=mock_session, region="us-west-2")
        assert model_id is not None
        assert isinstance(model_id, str)

    @patch("model_discovery._probe_model", return_value=False)
    def test_raises_runtime_error_when_no_models(self, mock_probe, mock_session):
        mock_session.client.return_value = MagicMock()

        with pytest.raises(RuntimeError, match="No Bedrock models available"):
            get_model_id("balanced", boto_session=mock_session, region="us-west-2")


class TestResolveModelKey:
    """Tests for resolve_model_key."""

    def test_resolves_legacy_keys_to_tiers(self, mock_session):
        client = MagicMock()
        client.exceptions = MagicMock()
        client.converse.return_value = {"output": {}}
        mock_session.client.return_value = client

        for key, expected_tier in _LEGACY_KEY_TO_TIER.items():
            result = resolve_model_key(key, boto_session=mock_session, region="us-west-2")
            assert result is not None, f"Key '{key}' (tier={expected_tier}) returned None"

    def test_passes_through_direct_model_ids(self, mock_session):
        direct_id = "us.anthropic.claude-sonnet-4-6"
        result = resolve_model_key(direct_id, boto_session=mock_session, region="us-west-2")
        assert result == direct_id

    def test_haiku_resolves_to_fast_tier(self, mock_session):
        def only_haiku(client, model_id):
            return "haiku" in model_id

        mock_session.client.return_value = MagicMock()
        with patch("model_discovery._probe_model", side_effect=only_haiku):
            result = resolve_model_key("haiku", boto_session=mock_session, region="us-west-2")
        assert "haiku" in result

    def test_opus_resolves_to_powerful_tier(self, mock_session):
        def only_opus(client, model_id):
            return "opus" in model_id

        mock_session.client.return_value = MagicMock()
        with patch("model_discovery._probe_model", side_effect=only_opus):
            result = resolve_model_key("opus", boto_session=mock_session, region="us-west-2")
        assert "opus" in result


class TestCandidateModels:
    """Tests for the candidate models list structure."""

    def test_all_candidates_have_three_fields(self):
        for entry in _CANDIDATE_MODELS:
            assert len(entry) == 3, f"Entry {entry} should have 3 fields"

    def test_all_tiers_are_valid(self):
        valid_tiers = {"fast", "balanced", "powerful"}
        for model_id, name, tier in _CANDIDATE_MODELS:
            assert tier in valid_tiers, f"Invalid tier '{tier}' for {model_id}"

    def test_each_tier_has_candidates(self):
        tiers = {tier for _, _, tier in _CANDIDATE_MODELS}
        assert "fast" in tiers
        assert "balanced" in tiers
        assert "powerful" in tiers

    def test_powerful_candidates_come_first(self):
        """Candidates are ordered: powerful first, then balanced, then fast."""
        tier_order = []
        seen = set()
        for _, _, tier in _CANDIDATE_MODELS:
            if tier not in seen:
                tier_order.append(tier)
                seen.add(tier)
        assert tier_order == ["powerful", "balanced", "fast"]

    def test_all_model_ids_are_us_prefix(self):
        for model_id, _, _ in _CANDIDATE_MODELS:
            assert model_id.startswith("us.anthropic."), f"{model_id} missing us.anthropic. prefix"


class TestLegacyKeyMapping:
    """Tests for legacy key → tier mapping."""

    def test_haiku_maps_to_fast(self):
        assert _LEGACY_KEY_TO_TIER["haiku"] == "fast"

    def test_sonnet_maps_to_balanced(self):
        assert _LEGACY_KEY_TO_TIER["sonnet"] == "balanced"

    def test_opus_maps_to_powerful(self):
        assert _LEGACY_KEY_TO_TIER["opus"] == "powerful"

    def test_all_keys_map_to_valid_tiers(self):
        valid_tiers = {"fast", "balanced", "powerful"}
        for key, tier in _LEGACY_KEY_TO_TIER.items():
            assert tier in valid_tiers, f"Key '{key}' maps to invalid tier '{tier}'"
