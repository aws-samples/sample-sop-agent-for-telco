# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Tests for framework.registry — the kind-generic extension registry."""

import pytest

from amzn_cse_telco_autonomous_network_agents_app.agent.framework.contracts import (
    CommandIntegration,
)
from amzn_cse_telco_autonomous_network_agents_app.agent.framework.enums import (
    ExtensionKind,
    ResolutionMode,
)
from amzn_cse_telco_autonomous_network_agents_app.agent.framework.registry import (
    Registry,
)


class _GoodCli(CommandIntegration):
    @property
    def name(self) -> str:
        return "good"

    def run(self, command: str) -> str:
        return f"ran: {command}"


class _NotACli:
    """Does not satisfy CommandIntegration."""


class TestDefineKind:
    def test_redeclare_identical_is_idempotent(self):
        reg = Registry()
        reg.define_kind(ExtensionKind.TOOL, mode=ResolutionMode.COLLECT)
        # same mode/contract again — allowed, no raise
        reg.define_kind(ExtensionKind.TOOL, mode=ResolutionMode.COLLECT)
        assert ExtensionKind.TOOL in reg.kinds()

    def test_conflicting_redeclare_raises(self):
        reg = Registry()
        reg.define_kind(ExtensionKind.TOOL, mode=ResolutionMode.COLLECT)
        with pytest.raises(ValueError, match="different mode"):
            reg.define_kind(ExtensionKind.TOOL, mode=ResolutionMode.SELECT)


class TestRegister:
    def test_register_and_get_all_collect(self):
        reg = Registry()
        reg.define_kind(ExtensionKind.TOOL, mode=ResolutionMode.COLLECT)
        reg.register(ExtensionKind.TOOL, "a", object())
        reg.register(ExtensionKind.TOOL, "b", object())
        assert len(reg.get_all(ExtensionKind.TOOL)) == 2
        assert reg.names(ExtensionKind.TOOL) == ["a", "b"]

    def test_register_undeclared_kind_raises(self):
        reg = Registry()
        with pytest.raises(KeyError, match="not declared"):
            reg.register(ExtensionKind.TOOL, "a", object())

    def test_duplicate_registration_raises(self):
        reg = Registry()
        reg.define_kind(ExtensionKind.TOOL, mode=ResolutionMode.COLLECT)
        reg.register(ExtensionKind.TOOL, "dup", object())
        with pytest.raises(ValueError, match="Duplicate registration"):
            reg.register(ExtensionKind.TOOL, "dup", object())

    def test_override_replaces(self):
        reg = Registry()
        reg.define_kind(ExtensionKind.TOOL, mode=ResolutionMode.COLLECT)
        first, second = object(), object()
        reg.register(ExtensionKind.TOOL, "x", first)
        reg.register(ExtensionKind.TOOL, "x", second, override=True)
        assert reg.get_all(ExtensionKind.TOOL) == [second]

    def test_empty_name_raises(self):
        reg = Registry()
        reg.define_kind(ExtensionKind.TOOL, mode=ResolutionMode.COLLECT)
        with pytest.raises(ValueError, match="empty name"):
            reg.register(ExtensionKind.TOOL, "", object())


class TestContractValidation:
    def test_instance_satisfying_contract_ok(self):
        reg = Registry()
        reg.define_kind(
            ExtensionKind.CLI,
            mode=ResolutionMode.SELECT,
            contract=CommandIntegration,
        )
        reg.register(ExtensionKind.CLI, "good", _GoodCli())
        assert reg.get_one(ExtensionKind.CLI, "good").run("x") == "ran: x"

    def test_class_instead_of_instance_rejected(self):
        # Contract kinds accept INSTANCES only. Registering the class itself
        # would let get_one return an uninstantiated type whose methods mis-bind
        # on first call — the first-use failure boot-time validation prevents.
        reg = Registry()
        reg.define_kind(
            ExtensionKind.CLI,
            mode=ResolutionMode.SELECT,
            contract=CommandIntegration,
        )
        with pytest.raises(TypeError, match="must be an INSTANCE"):
            reg.register(ExtensionKind.CLI, "cls", _GoodCli)

    def test_contract_violation_raises_at_registration(self):
        reg = Registry()
        reg.define_kind(
            ExtensionKind.CLI,
            mode=ResolutionMode.SELECT,
            contract=CommandIntegration,
        )
        with pytest.raises(TypeError, match="must be an INSTANCE"):
            reg.register(ExtensionKind.CLI, "bad", _NotACli())


class TestResolution:
    def test_get_one_unknown_name_raises_with_known_list(self):
        reg = Registry()
        reg.define_kind(ExtensionKind.CLI, mode=ResolutionMode.SELECT)
        reg.register(ExtensionKind.CLI, "known", object())
        with pytest.raises(KeyError, match="known"):
            reg.get_one(ExtensionKind.CLI, "missing")

    def test_get_one_on_collect_kind_raises(self):
        reg = Registry()
        reg.define_kind(ExtensionKind.TOOL, mode=ResolutionMode.COLLECT)
        reg.register(ExtensionKind.TOOL, "a", object())
        with pytest.raises(ValueError, match="only valid for SELECT"):
            reg.get_one(ExtensionKind.TOOL, "a")

    def test_get_all_on_select_kind_raises(self):
        reg = Registry()
        reg.define_kind(ExtensionKind.CLI, mode=ResolutionMode.SELECT)
        with pytest.raises(ValueError, match="only valid for COLLECT"):
            reg.get_all(ExtensionKind.CLI)

    def test_get_all_empty_when_nothing_registered(self):
        reg = Registry()
        reg.define_kind(ExtensionKind.TOOL, mode=ResolutionMode.COLLECT)
        assert reg.get_all(ExtensionKind.TOOL) == []

    def test_undeclared_kind_resolution_raises(self):
        reg = Registry()
        with pytest.raises(KeyError, match="not declared"):
            reg.get_all(ExtensionKind.TOOL)


class TestContractsAbc:
    def test_command_integration_not_instantiable(self):
        # The ABC cannot be instantiated directly (abstract methods unimplemented).
        with pytest.raises(TypeError):
            CommandIntegration()  # type: ignore[abstract]


class TestGlobalRegistryStandardKinds:
    """The module-global registry declares the framework's standard kinds at import."""

    def test_standard_kinds_declared(self):
        from amzn_cse_telco_autonomous_network_agents_app.agent.framework.registry import (
            registry,
        )

        declared = set(registry.kinds())
        assert {
            ExtensionKind.TOOL,
            ExtensionKind.AGENT_ROLE,
            ExtensionKind.CLI,
        } <= declared

    def test_cli_kind_enforces_contract_on_global_registry(self):
        from amzn_cse_telco_autonomous_network_agents_app.agent.framework.registry import (
            registry,
        )

        with pytest.raises(TypeError, match="must be an INSTANCE"):
            registry.register(ExtensionKind.CLI, "bad_global", _NotACli())
