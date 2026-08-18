# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Framework vocabulary — the closed sets of valid string values.

Single source of truth for every string that has a fixed set of valid values.
Code references these members (e.g. ``AgentRole.ANRA``) instead of bare string
literals, and config validation checks membership against the enum instead of a
hand-maintained parallel list. This is model-driven: add a value here once and
both the validator and the registry pick it up — there is no second list to keep
in sync.

All are ``StrEnum`` so ``AgentRole.ANRA == "anra"`` is true. YAML values stay
plain human-readable strings; the enum only governs the code side. A helper,
``values()``, returns the set of valid strings for a membership check.
"""

from __future__ import annotations

from enum import StrEnum


class _ValuesMixin(StrEnum):
    """StrEnum with a ``values()`` classmethod for membership checks.

    ``"auto" in ApprovalMode.values()`` is the canonical "is this config string
    valid?" check used by validation, so validators never re-list literals.
    """

    @classmethod
    def values(cls) -> frozenset[str]:
        """Return the frozenset of valid string values for this enum."""
        return frozenset(member.value for member in cls)


# ── Framework-level vocabularies (consumed by the registry + entrypoint) ──


class ResolutionMode(_ValuesMixin):
    """How a registered extension kind is resolved at read time."""

    SELECT = "select"  # pick exactly one of N by a config-driven key (get_one)
    COLLECT = "collect"  # gather all registered implementations (get_all)


class ExtensionKind(_ValuesMixin):
    """The declared extension points — the seams where behavior can vary.

    This set IS the abstraction layer: each member is a place the engine talks
    through an adapter/tool rather than a hardcoded value. Adding a member here
    declares a new kind of pluggability (rare, framework-level work).
    """

    TOOL = "tool"  # COLLECT — agent tools (Strands @tool callables)
    CLI = "cli"  # SELECT  — site/vendor CLI integration (e.g. telcocli)
    TOPOLOGY = "topology"  # SELECT  — node/NF topology backend (yaml | neptune)
    METRIC_SOURCE = "metric_source"  # SELECT — KPI/alarm query backend
    MODEL = "model"  # SELECT  — model provider/resolver
    AGENT_ROLE = "agent_role"  # COLLECT — background-loop roles (deferred by policy)


class AgentRole(_ValuesMixin):
    """The agent roles selectable via the ``AGENT_ROLE`` env var.

    Source of truth for what was the ``_VALID_ROLES`` set in entrypoint.
    """

    ANRA = "anra"  # remediation
    ANDA = "anda"  # deployment
    ANPA = "anpa"  # provisioning


# ── Config-value vocabularies (defined now; wired into config.validate() in a
#    later CR alongside selector validation — kept here so there is one home and
#    no parallel literal lists when that wiring lands). ──


class ApprovalMode(_ValuesMixin):
    """Remediation approval gate mode (config ``approval.mode``)."""

    AUTO = "auto"  # execute without human approval
    MANUAL = "manual"  # queue for in-product human approval
    GITLAB = "gitlab"  # gate via GitLab/GitHub issue approval


class TopologyProviderKind(_ValuesMixin):
    """Topology backend selector (config ``topology.provider``)."""

    YAML = "yaml"  # single-site, flat node list from agent-config.yaml
    NEPTUNE = "neptune"  # multi-site graph from Amazon Neptune


class RemediationMode(_ValuesMixin):
    """How remediation actions are applied (config ``remediation.mode``)."""

    DIRECT = "direct"  # apply changes directly (kubectl/ssm/redfish)
    GITOPS = "gitops"  # propose changes through a GitOps flow


class ModelTier(_ValuesMixin):
    """Logical model tier resolved to a concrete Bedrock model ID."""

    FAST = "fast"  # haiku-class — tool use, fast responses
    SMART = "smart"  # sonnet-class — complex reasoning
