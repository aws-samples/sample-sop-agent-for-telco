# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Tests for framework.plugin_loader — config-driven plugin discovery.

The happy-path test imports a fixture module by dotted path and asserts its tool
lands in the global registry — the exact path a customer plugin follows. The
failure tests assert a bad/listed-but-broken module fails loud at boot.
"""

import sys

import pytest

from amzn_cse_telco_autonomous_network_agents_app.agent.framework.enums import (
    ExtensionKind,
)
from amzn_cse_telco_autonomous_network_agents_app.agent.framework.plugin_loader import (
    PluginLoadError,
    load_plugins,
)
from amzn_cse_telco_autonomous_network_agents_app.agent.framework.registry import (
    registry,
)

_FIXTURE = "fixtures.sample_plugin"
_BROKEN = "fixtures.broken_plugin"


@pytest.fixture(autouse=True)
def _hermetic_registry():
    """Make each test hermetic against the module-global registry.

    These tests import fixture plugins that self-register into the singleton
    `registry` as a one-time import side effect. Two things must be reset around
    each test: (1) the registry's items, so registrations don't leak to other
    tests/files and make the suite order-dependent; (2) the fixture modules in
    `sys.modules`, so a test that relies on the import (and thus the decorator)
    actually firing isn't defeated by Python's import caching from an earlier
    test. Reaching into `_kinds` is acceptable for an isolation fixture (it is
    the registry's own test surface).
    """
    saved = {kind: dict(spec.items) for kind, spec in registry._kinds.items()}
    for mod in (_FIXTURE, _BROKEN):
        sys.modules.pop(mod, None)
    yield
    for kind, spec in registry._kinds.items():
        spec.items.clear()
        spec.items.update(saved.get(kind, {}))
    for mod in (_FIXTURE, _BROKEN):
        sys.modules.pop(mod, None)


class TestLoadPlugins:
    def test_empty_list_is_noop(self):
        assert load_plugins([]) == []

    def test_blank_entries_skipped(self):
        assert load_plugins(["", "   "]) == []

    def test_loads_fixture_and_registers_tool(self):
        from fixtures.sample_plugin import SAMPLE_PLUGIN_TOOL_NAME

        loaded = load_plugins([_FIXTURE])
        assert loaded == [_FIXTURE]
        # The fixture's @register_tool ran on import → tool is in the registry.
        assert SAMPLE_PLUGIN_TOOL_NAME in registry.names(ExtensionKind.TOOL)

    def test_idempotent_reload_does_not_double_register(self):
        # Re-importing an already-imported module is a no-op for Python, so the
        # decorator does not fire twice and registration does not raise.
        load_plugins([_FIXTURE])
        load_plugins([_FIXTURE])
        from fixtures.sample_plugin import SAMPLE_PLUGIN_TOOL_NAME

        names = registry.names(ExtensionKind.TOOL)
        assert names.count(SAMPLE_PLUGIN_TOOL_NAME) == 1

    def test_unknown_module_fails_loud(self):
        with pytest.raises(PluginLoadError, match="no.such.module"):
            load_plugins(["no.such.module"])

    def test_module_with_import_error_fails_loud(self):
        # A module that raises on import must surface, not be swallowed.
        with pytest.raises(PluginLoadError, match="fixtures.broken_plugin"):
            load_plugins(["fixtures.broken_plugin"])
