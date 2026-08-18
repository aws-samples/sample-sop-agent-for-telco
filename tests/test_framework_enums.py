# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Tests for framework.enums — the framework vocabulary."""

from amzn_cse_telco_autonomous_network_agents_app.agent.framework.enums import (
    AgentRole,
    ApprovalMode,
    ExtensionKind,
    ModelTier,
    RemediationMode,
    ResolutionMode,
    TopologyProviderKind,
)


class TestStrEnumBehavior:
    def test_members_equal_their_string(self):
        # StrEnum: member compares equal to its raw string, so YAML strings and
        # enum references interoperate without conversion.
        assert AgentRole.ANRA == "anra"
        assert ApprovalMode.AUTO == "auto"
        assert ModelTier.FAST == "fast"

    def test_values_returns_frozenset_of_strings(self):
        assert AgentRole.values() == frozenset({"anra", "anda", "anpa"})
        assert "auto" in ApprovalMode.values()
        assert "bogus" not in ApprovalMode.values()


class TestVocabularyContents:
    def test_agent_roles(self):
        assert AgentRole.values() == frozenset({"anra", "anda", "anpa"})

    def test_resolution_modes(self):
        assert ResolutionMode.values() == frozenset({"select", "collect"})

    def test_extension_kinds_cover_declared_seams(self):
        assert {"tool", "cli", "topology", "metric_source", "model", "agent_role"} == (ExtensionKind.values())

    def test_config_value_enums(self):
        assert TopologyProviderKind.values() == frozenset({"yaml", "neptune"})
        assert RemediationMode.values() == frozenset({"direct", "gitops"})
        assert ModelTier.values() == frozenset({"fast", "smart"})
        assert ApprovalMode.values() == frozenset({"auto", "manual", "gitlab"})
