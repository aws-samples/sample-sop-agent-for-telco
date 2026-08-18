# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Tests for the model-factory consolidation arc.

Six inline hardcoded `fast`-tier model IDs (monitor.py x3, correlator.py,
the anomaly detector, routers/chat.py) were collapsed onto a single
factory `core.model_resolver.build_model(...)` that performs resolve + session +
BedrockModel construction in one place, replacing the repeated
`aws_session(...)` + `BedrockModel(model_id=get_model(...), ...)` boilerplate.

The bare `"fast"`/`"smart"` tier selectors were replaced with the
`ModelTier` StrEnum (framework/enums.py). `get_model`/`build_model` params are
typed as `ModelTier`, and call sites pass `ModelTier.FAST`/`ModelTier.SMART`.
Because `ModelTier` is a StrEnum, the change is backward compatible — config
strings and env vars (always plain strings) still resolve identically; see
TestModelTierInterop.

Things pinned here:

1. The no-config-change guarantee: with no env override, no config store, and the
   preferred fast model available, `get_model("fast")` resolves to the SAME Haiku
   ID that was previously hardcoded — so behavior is identical out of the box.
2. `build_model` resolves via `get_model(tier)`, builds the session via the
   project's `aws_session` convention, and wraps the resolved ID in a BedrockModel.
3. The call sites no longer carry an inline model literal and do consult
   `build_model("fast")`. These modules are in the ruff/mypy exclude set (legacy
   ported code) and constructing their Strands agents pulls in bedrock, so this
   is asserted at the source level rather than by executing the agents.
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# model_resolver imports boto3 at module level; stub it if absent (matches
# the pattern in test_config_wiring.py).
if "boto3" not in sys.modules:
    sys.modules["boto3"] = MagicMock()

from amzn_cse_telco_autonomous_network_agents_app.agent.core import model_resolver

# The exact ID that was hardcoded at all six call sites before this change, and
# the first entry of _PREFERRED_FAST — the resolver must still return it when
# nothing overrides and it is available.
_PREVIOUSLY_HARDCODED_FAST = "us.anthropic.claude-haiku-4-5-20251001-v1:0"

_AGENT_ROOT = (
    Path(__file__).resolve().parent.parent
    / "src"
    / "amzn_cse_telco_autonomous_network_agents_app"
    / "agent"
)

_CONVERTED_SITES = [
    _AGENT_ROOT / "monitor.py",
    _AGENT_ROOT / "correlator.py",
    _AGENT_ROOT / "agents" / "anra" / "monitoring" / "anomaly_detection.py",
    _AGENT_ROOT / "routers" / "chat.py",
]

# Expected number of build_model(ModelTier.FAST) call sites per converted module.
# Pinning exact counts (not just presence) means a partial revert — e.g. 2 of
# monitor.py's 3 sites reverted to an inline literal — fails loudly here rather
# than relying solely on test_no_inline_fast_model_literal_remains as a backstop.
_EXPECTED_FAST_CALLS = {
    # monitor.py had 3; the anomaly-classify site moved to anomaly_detection.py
    # when the ANRA anomaly cluster was extracted, leaving 2 here.
    _AGENT_ROOT / "monitor.py": 2,
    _AGENT_ROOT / "correlator.py": 1,
    _AGENT_ROOT / "agents" / "anra" / "monitoring" / "anomaly_detection.py": 1,
    _AGENT_ROOT / "routers" / "chat.py": 1,
}


class TestNoConfigChangeGuarantee:
    @pytest.fixture(autouse=True)
    def _clear_cache(self):
        model_resolver.invalidate_cache()
        yield
        model_resolver.invalidate_cache()

    def test_fast_resolves_to_previously_hardcoded_id(self, monkeypatch):
        # No env override, no config store, preferred fast model is available:
        # the resolver returns exactly what used to be hardcoded.
        monkeypatch.delenv("BEDROCK_MODEL_ID", raising=False)
        monkeypatch.delenv("BEDROCK_MODEL_TIER", raising=False)
        with patch(
            "amzn_cse_telco_autonomous_network_agents_app.agent.core.config_store.get_config",
            return_value=None,
        ), patch(
            "amzn_cse_telco_autonomous_network_agents_app.agent.core.model_resolver._list_active_profiles",
            return_value={_PREVIOUSLY_HARDCODED_FAST},
        ):
            assert model_resolver.get_model("fast") == _PREVIOUSLY_HARDCODED_FAST

    def test_fast_falls_back_to_hardcoded_id_when_listing_empty(self, monkeypatch):
        # Bedrock listing succeeds but returns no active profiles: the resolver
        # must still fall back to the previously hardcoded ID (_PREFERRED_FAST[0]).
        # This is the real behavior-preservation path, not the happy match above.
        monkeypatch.delenv("BEDROCK_MODEL_ID", raising=False)
        monkeypatch.delenv("BEDROCK_MODEL_TIER", raising=False)
        with patch(
            "amzn_cse_telco_autonomous_network_agents_app.agent.core.config_store.get_config",
            return_value=None,
        ), patch(
            "amzn_cse_telco_autonomous_network_agents_app.agent.core.model_resolver._list_active_profiles",
            return_value=set(),
        ):
            assert model_resolver.get_model("fast") == _PREVIOUSLY_HARDCODED_FAST

    def test_fast_falls_back_to_hardcoded_id_when_listing_raises(self, monkeypatch):
        # bedrock:ListInferenceProfiles denied/unavailable: _list_active_profiles
        # swallows the exception and returns set(), so get_model still preserves
        # the old hardcoded ID. Pins the IAM-missing safety path explicitly.
        monkeypatch.delenv("BEDROCK_MODEL_ID", raising=False)
        monkeypatch.delenv("BEDROCK_MODEL_TIER", raising=False)
        failing_client = MagicMock()
        failing_client.list_inference_profiles.side_effect = Exception("AccessDenied")
        with patch(
            "amzn_cse_telco_autonomous_network_agents_app.agent.core.config_store.get_config",
            return_value=None,
        ), patch.object(model_resolver.boto3, "client", return_value=failing_client):
            assert model_resolver.get_model("fast") == _PREVIOUSLY_HARDCODED_FAST

    def test_fast_is_first_preference(self):
        # Guards the guarantee above: if someone reorders _PREFERRED_FAST so the
        # old hardcoded ID is no longer first, the no-config-change promise breaks
        # and this test makes that explicit.
        assert model_resolver._PREFERRED_FAST[0] == _PREVIOUSLY_HARDCODED_FAST


class TestCallSitesConsultResolver:
    def test_no_inline_fast_model_literal_remains(self):
        # None of the converted sites should still carry the inline literal.
        offenders = [
            str(p) for p in _CONVERTED_SITES if _PREVIOUSLY_HARDCODED_FAST in p.read_text()
        ]
        assert not offenders, f"inline model literal still present in: {offenders}"

    def test_converted_sites_call_build_model_fast(self):
        # Each converted module must call build_model(ModelTier.FAST) exactly as many
        # times as it had inline literals, so a partial revert fails here directly.
        wrong = {
            str(p): (p.read_text().count("build_model(ModelTier.FAST)"), expected)
            for p, expected in _EXPECTED_FAST_CALLS.items()
            if p.read_text().count("build_model(ModelTier.FAST)") != expected
        }
        assert not wrong, f"build_model(ModelTier.FAST) count (actual, expected) mismatched: {wrong}"


class TestBuildModel:
    """build_model resolves the tier, builds the session, and wraps a BedrockModel."""

    def test_build_model_resolves_tier_and_builds_session(self, monkeypatch):
        # build_model should call get_model(tier) for the ID and aws_session for the
        # session, then construct BedrockModel(model_id=<resolved>, boto_session=<session>).
        fake_session = object()
        captured = {}

        def fake_bedrock_model(*, model_id, boto_session):
            captured["model_id"] = model_id
            captured["boto_session"] = boto_session
            return ("model", model_id)

        strands_bedrock = MagicMock()
        strands_bedrock.BedrockModel = fake_bedrock_model
        monkeypatch.setitem(sys.modules, "strands", MagicMock())
        monkeypatch.setitem(sys.modules, "strands.models", MagicMock())
        monkeypatch.setitem(sys.modules, "strands.models.bedrock", strands_bedrock)

        with patch.object(model_resolver, "get_model", return_value="resolved-id") as gm, patch(
            "amzn_cse_telco_autonomous_network_agents_app.agent.util.aws.aws_session",
            return_value=fake_session,
        ) as sess:
            result = model_resolver.build_model("fast", profile="p", region="r")

        gm.assert_called_once_with("fast")
        sess.assert_called_once_with("p", "r")
        assert captured["model_id"] == "resolved-id"
        assert captured["boto_session"] is fake_session
        assert result == ("model", "resolved-id")

    def test_build_model_defaults_profile_region_from_env(self, monkeypatch):
        # With no explicit profile/region, build_model falls back to the BEDROCK_*
        # env vars (the convention every converted call site previously used inline).
        monkeypatch.setenv("BEDROCK_PROFILE", "envprof")
        monkeypatch.setenv("BEDROCK_REGION", "us-east-1")

        strands_bedrock = MagicMock()
        strands_bedrock.BedrockModel = lambda *, model_id, boto_session: None
        monkeypatch.setitem(sys.modules, "strands", MagicMock())
        monkeypatch.setitem(sys.modules, "strands.models", MagicMock())
        monkeypatch.setitem(sys.modules, "strands.models.bedrock", strands_bedrock)

        with patch.object(model_resolver, "get_model", return_value="x"), patch(
            "amzn_cse_telco_autonomous_network_agents_app.agent.util.aws.aws_session",
            return_value=object(),
        ) as sess:
            model_resolver.build_model("fast")

        sess.assert_called_once_with("envprof", "us-east-1")

    def test_empty_profile_collapses_to_none_end_to_end(self, monkeypatch):
        # The behavior-preservation crux: with no profile set, the real aws_session
        # (NOT stubbed here) must collapse the empty string to profile_name=None, so
        # boto3 uses the default credential chain exactly as the old inline sites did.
        monkeypatch.delenv("BEDROCK_PROFILE", raising=False)
        monkeypatch.setenv("BEDROCK_REGION", "us-west-2")
        captured = {}

        fake_boto3 = MagicMock()

        def fake_session_ctor(*, profile_name, region_name):
            captured["profile_name"] = profile_name
            captured["region_name"] = region_name
            return object()

        fake_boto3.Session = fake_session_ctor

        strands_bedrock = MagicMock()
        strands_bedrock.BedrockModel = lambda *, model_id, boto_session: None
        monkeypatch.setitem(sys.modules, "strands", MagicMock())
        monkeypatch.setitem(sys.modules, "strands.models", MagicMock())
        monkeypatch.setitem(sys.modules, "strands.models.bedrock", strands_bedrock)

        # Patch boto3 inside util.aws so the real aws_session collapse logic runs.
        with patch.object(model_resolver, "get_model", return_value="x"), patch(
            "amzn_cse_telco_autonomous_network_agents_app.agent.util.aws.boto3", fake_boto3
        ):
            model_resolver.build_model("fast")

        assert captured["profile_name"] is None
        assert captured["region_name"] == "us-west-2"


class TestModelTierInterop:
    """The tier params are typed as ModelTier (StrEnum). Enum members and the
    plain "fast"/"smart" strings must be interchangeable, so config/env values
    (always strings) and code (using the enum) resolve identically — the
    backward-compatibility guarantee of this change.
    """

    @pytest.fixture(autouse=True)
    def _clear_cache(self):
        model_resolver.invalidate_cache()
        yield
        model_resolver.invalidate_cache()

    def test_modeltier_member_equals_plain_string(self):
        from amzn_cse_telco_autonomous_network_agents_app.agent.framework.enums import (
            ModelTier,
        )

        assert ModelTier.FAST == "fast"
        assert ModelTier.SMART == "smart"

    def test_enum_and_string_resolve_to_same_model(self, monkeypatch):
        # get_model(ModelTier.FAST) and get_model("fast") must return the same ID.
        from amzn_cse_telco_autonomous_network_agents_app.agent.framework.enums import (
            ModelTier,
        )

        monkeypatch.delenv("BEDROCK_MODEL_ID", raising=False)
        monkeypatch.delenv("BEDROCK_MODEL_TIER", raising=False)
        with patch(
            "amzn_cse_telco_autonomous_network_agents_app.agent.core.config_store.get_config",
            return_value=None,
        ), patch(
            "amzn_cse_telco_autonomous_network_agents_app.agent.core.model_resolver._list_active_profiles",
            return_value={_PREVIOUSLY_HARDCODED_FAST},
        ):
            via_enum = model_resolver.get_model(ModelTier.FAST)
            model_resolver.invalidate_cache()
            via_str = model_resolver.get_model("fast")
        assert via_enum == via_str == _PREVIOUSLY_HARDCODED_FAST

    def test_config_string_tier_still_selects_preference_list(self, monkeypatch):
        # Guards the riskiest line of the ModelTier swap: the config-string
        # coercion branch `ModelTier(cfg.bedrock_model_tier)` gated by
        # `in ModelTier.values()`. A plain "smart" string from config must still
        # override the caller's enum arg and route to the smart preference list,
        # exactly as the old `in ("fast","smart")` tuple check did.
        from amzn_cse_telco_autonomous_network_agents_app.agent.config import SiteConfig
        from amzn_cse_telco_autonomous_network_agents_app.agent.framework.enums import (
            ModelTier,
        )

        smart_id = model_resolver._PREFERRED_SMART[0]
        monkeypatch.delenv("BEDROCK_MODEL_ID", raising=False)
        monkeypatch.delenv("BEDROCK_MODEL_TIER", raising=False)
        cfg = SiteConfig(bedrock_model_override="", bedrock_model_tier="smart")
        with patch(
            "amzn_cse_telco_autonomous_network_agents_app.agent.core.config_store.get_config",
            return_value=cfg,
        ), patch(
            "amzn_cse_telco_autonomous_network_agents_app.agent.core.model_resolver._list_active_profiles",
            return_value={smart_id},
        ):
            # caller passes FAST, but config "smart" string must win and select smart
            assert model_resolver.get_model(ModelTier.FAST) == smart_id


class TestBuildProbedModel:
    """build_probed_model (moved from sop_graph._create_model): probe the
    model with a 1-token converse(), cascade through _MODEL_FALLBACKS on a
    Legacy/ResourceNotFound error, raise anything else, and cache per
    (model_id, region).
    """

    @pytest.fixture(autouse=True)
    def _clear_cache(self):
        model_resolver.invalidate_cache()
        yield
        model_resolver.invalidate_cache()

    def _session(self, converse_side_effect, region="us-east-1"):
        # A fake boto session whose bedrock-runtime client's converse() is driven
        # by the given side effect. region_name mirrors a real boto3 session.
        client = MagicMock()
        client.converse.side_effect = converse_side_effect
        session = MagicMock()
        session.region_name = region
        session.client.return_value = client
        return session, client

    def _stub_bedrockmodel(self, monkeypatch):
        # build_probed_model does `from strands.models.bedrock import BedrockModel`.
        captured = {}
        mod = MagicMock()
        mod.BedrockModel = lambda *, model_id, boto_session: captured.setdefault(
            "model_id", model_id
        )
        monkeypatch.setitem(sys.modules, "strands", MagicMock())
        monkeypatch.setitem(sys.modules, "strands.models", MagicMock())
        monkeypatch.setitem(sys.modules, "strands.models.bedrock", mod)
        return captured

    def test_first_model_ok_no_fallback(self, monkeypatch):
        captured = self._stub_bedrockmodel(monkeypatch)
        session, client = self._session(converse_side_effect=[{"ok": True}])
        model_resolver.build_probed_model("model-a", session)
        assert captured["model_id"] == "model-a"
        assert client.converse.call_count == 1

    def test_cascades_on_legacy_error(self, monkeypatch):
        captured = self._stub_bedrockmodel(monkeypatch)
        start = "us.anthropic.claude-sonnet-4-20250514-v1:0"
        expected_next = model_resolver._MODEL_FALLBACKS[start]
        # First probe raises a "Legacy" error, second succeeds.
        session, client = self._session(
            converse_side_effect=[Exception("This model is Legacy"), {"ok": True}]
        )
        model_resolver.build_probed_model(start, session)
        assert captured["model_id"] == expected_next
        assert client.converse.call_count == 2

    def test_cascades_on_resource_not_found(self, monkeypatch):
        captured = self._stub_bedrockmodel(monkeypatch)
        start = "us.anthropic.claude-sonnet-4-20250514-v1:0"
        expected_next = model_resolver._MODEL_FALLBACKS[start]

        class ResourceNotFoundException(Exception):
            pass

        session, _ = self._session(
            converse_side_effect=[ResourceNotFoundException("gone"), {"ok": True}]
        )
        model_resolver.build_probed_model(start, session)
        assert captured["model_id"] == expected_next

    def test_non_fallback_error_raises(self, monkeypatch):
        self._stub_bedrockmodel(monkeypatch)
        session, _ = self._session(
            converse_side_effect=[Exception("AccessDeniedException")]
        )
        with pytest.raises(Exception, match="AccessDenied"):
            model_resolver.build_probed_model("model-a", session)

    def test_exhausted_chain_raises_single_hop(self, monkeypatch):
        self._stub_bedrockmodel(monkeypatch)
        # A model with no fallback entry that fails Legacy -> fallback is None,
        # loop ends immediately.
        session, _ = self._session(converse_side_effect=[Exception("Legacy")])
        with pytest.raises(RuntimeError, match="fallbacks exhausted"):
            model_resolver.build_probed_model("no-fallback-model", session)

    def test_exhausted_walks_real_chain_to_terminal(self, monkeypatch):
        # Start mid-chain and confirm it walks the real _MODEL_FALLBACKS to its
        # terminal (claude-opus-4-6-v1, which has no entry) then raises. Pins the
        # actual chain tail, so breaking the end of _MODEL_FALLBACKS fails here.
        self._stub_bedrockmodel(monkeypatch)
        start = "us.anthropic.claude-sonnet-4-5-20250929-v1:0"
        # Every probe fails Legacy: walks start -> opus-4 -> opus-4-6 -> None.
        session, client = self._session(converse_side_effect=Exception("Legacy"))
        with pytest.raises(RuntimeError, match="fallbacks exhausted"):
            model_resolver.build_probed_model(start, session)
        assert client.converse.call_count == 3  # start + 2 fallbacks

    def test_result_cached_returns_resolved_id_after_cascade(self, monkeypatch):
        # The cache must store/return the RESOLVED id (post-cascade), not the
        # requested one. First call cascades A->B; a second call for A returns B
        # with no re-probe.
        captured = self._stub_bedrockmodel(monkeypatch)
        start = "us.anthropic.claude-sonnet-4-20250514-v1:0"
        resolved = model_resolver._MODEL_FALLBACKS[start]
        session, client = self._session(
            converse_side_effect=[Exception("Legacy"), {"ok": True}]
        )
        model_resolver.build_probed_model(start, session)
        assert captured["model_id"] == resolved
        assert client.converse.call_count == 2
        model_resolver.build_probed_model(start, session)  # original id -> cache
        assert captured["model_id"] == resolved
        assert client.converse.call_count == 2  # no new probe

    def test_result_cached_per_model_region(self, monkeypatch):
        captured = self._stub_bedrockmodel(monkeypatch)
        session, client = self._session(converse_side_effect=[{"ok": True}])
        model_resolver.build_probed_model("model-a", session)
        # Second call for same (model, region) must not probe again.
        model_resolver.build_probed_model("model-a", session)
        assert client.converse.call_count == 1
        assert captured["model_id"] == "model-a"
