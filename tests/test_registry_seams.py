# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Tests for the S2.8 registry SELECT-seam migrations (CSE-3080).

Two engine seams now resolve through the extension registry instead of a
hardcoded branch:
  * the telcocli tool -> registry.get_one(CLI, cfg.cli_integration)
  * topology.get_provider -> registry.get_one(TOPOLOGY, cfg.topology_provider)

Both keep the previous behavior for a default config and let a customer swap the
implementation by config selector (or a registered plugin) without editing core.
"""

import sys
from unittest.mock import MagicMock, patch

import pytest

if "boto3" not in sys.modules:
    sys.modules["boto3"] = MagicMock()

from amzn_cse_telco_autonomous_network_agents_app.agent import topology
from amzn_cse_telco_autonomous_network_agents_app.agent.config import SiteConfig
from amzn_cse_telco_autonomous_network_agents_app.agent.framework.enums import (
    ExtensionKind,
)
from amzn_cse_telco_autonomous_network_agents_app.agent.framework.registry import (
    registry,
)


class TestCliIntegrationSeam:
    def test_telcocli_registered_as_command_integration(self):
        from amzn_cse_telco_autonomous_network_agents_app.agent.core import (
            executor,  # noqa: F401
        )
        from amzn_cse_telco_autonomous_network_agents_app.agent.framework.contracts import (
            CommandIntegration,
        )

        integ = registry.get_one(ExtensionKind.CLI, "telcocli")
        assert isinstance(integ, CommandIntegration)
        assert integ.name == "telcocli"

    def test_run_uses_config_profile_and_region(self):
        from amzn_cse_telco_autonomous_network_agents_app.agent.core import executor
        from amzn_cse_telco_autonomous_network_agents_app.agent.core.executor import (
            CmdResult,
        )

        cfg = SiteConfig(cli_profile="acme", cli_region="eu-west-1")
        captured = {}

        def fake_run_cmd(cmd, *a, **k):
            captured["cmd"] = cmd
            return CmdResult("ok", "", 0)

        with patch.object(executor, "_get_site_config", return_value=cfg), patch.object(
            executor, "run_cmd", side_effect=fake_run_cmd
        ):
            result = registry.get_one(ExtensionKind.CLI, "telcocli").run("list-outposts")

        assert result.success is True
        assert result.output == "ok"
        assert "--profile acme --region eu-west-1" in captured["cmd"]
        assert captured["cmd"].endswith("list-outposts")

    def test_run_defaults_match_historical_hardcode(self):
        # Empty config values fall back to the values previously baked into the
        # engine ("nec" / "us-east-1") — the no-config-change guarantee.
        from amzn_cse_telco_autonomous_network_agents_app.agent.core import executor
        from amzn_cse_telco_autonomous_network_agents_app.agent.core.executor import (
            CmdResult,
        )

        cfg = SiteConfig(cli_profile="", cli_region="")
        captured = {}

        def fake_run_cmd(cmd, *a, **k):
            captured["cmd"] = cmd
            return CmdResult("ok", "", 0)

        with patch.object(executor, "_get_site_config", return_value=cfg), patch.object(
            executor, "run_cmd", side_effect=fake_run_cmd
        ):
            registry.get_one(ExtensionKind.CLI, "telcocli").run("health")

        assert "--profile nec --region us-east-1" in captured["cmd"]

    def test_run_reports_failure_on_nonzero_exit(self):
        # Regression guard: a failing telcocli command must surface success=False,
        # not be masked as success (CmdResult.output is never empty).
        from amzn_cse_telco_autonomous_network_agents_app.agent.core import executor
        from amzn_cse_telco_autonomous_network_agents_app.agent.core.executor import (
            CmdResult,
        )

        cfg = SiteConfig()
        with patch.object(executor, "_get_site_config", return_value=cfg), patch.object(
            executor, "run_cmd", return_value=CmdResult("", "boom", 1)
        ):
            result = registry.get_one(ExtensionKind.CLI, "telcocli").run("bad-cmd")

        assert result.success is False
        assert "boom" in result.output


class TestTopologySeam:
    @pytest.fixture(autouse=True)
    def _reset(self):
        topology._provider = None
        yield
        topology._provider = None

    def test_default_resolves_yaml_via_registry(self):
        p = topology.get_provider()
        assert type(p).__name__ == "YamlTopology"
        # and it came through the registry (keys are plain strings)
        assert "yaml" in registry.names(ExtensionKind.TOPOLOGY)

    def test_neptune_without_endpoint_falls_back_to_yaml(self):
        # Preserves pre-registry behavior: neptune selected but no endpoint -> yaml.
        cfg = SiteConfig(topology_provider="neptune", neptune_endpoint="")
        with patch(
            "amzn_cse_telco_autonomous_network_agents_app.agent.topology.load_config",
            return_value=cfg,
        ):
            p = topology.get_provider()
        assert type(p).__name__ == "YamlTopology"

    def test_neptune_with_endpoint_selects_neptune(self):
        cfg = SiteConfig(topology_provider="neptune", neptune_endpoint="neptune.example:8182")
        with patch(
            "amzn_cse_telco_autonomous_network_agents_app.agent.topology.load_config",
            return_value=cfg,
        ):
            p = topology.get_provider()
        assert type(p).__name__ == "NeptuneTopology"
