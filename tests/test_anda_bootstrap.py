# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Unit tests for ANDA infrastructure bootstrap functionality."""

import os
import sys
from dataclasses import dataclass
from unittest.mock import MagicMock, patch

# Stub strands before importing agent modules
sys.modules.setdefault("strands", MagicMock())

os.environ.setdefault("ANRA_CONFIG", "/dev/null")


@dataclass
class FakeCmdResult:
    success: bool
    output: str
    returncode: int = 0


class TestInfrastructureCatalog:
    """Tests for the infrastructure catalog in anda/config.py."""

    def test_catalog_has_entries(self):
        from amzn_cse_telco_autonomous_network_agents_app.agent.agents.anda.config import (
            INFRASTRUCTURE_CATALOG,
        )

        assert len(INFRASTRUCTURE_CATALOG) >= 4

    def test_catalog_entries_have_required_fields(self):
        from amzn_cse_telco_autonomous_network_agents_app.agent.agents.anda.config import (
            INFRASTRUCTURE_CATALOG,
        )

        for c in INFRASTRUCTURE_CATALOG:
            assert c.name
            assert c.type in ("infrastructure", "platform")
            assert c.install_method in ("helm", "kubectl_apply")
            assert c.source
            assert c.namespace
            assert isinstance(c.wave, int)
            assert isinstance(c.depends_on, list)

    def test_catalog_wave_ordering(self):
        from amzn_cse_telco_autonomous_network_agents_app.agent.agents.anda.config import (
            INFRASTRUCTURE_CATALOG,
        )

        infra = [c for c in INFRASTRUCTURE_CATALOG if c.type == "infrastructure"]
        for c in infra:
            for dep in c.depends_on:
                dep_comp = next((x for x in infra if x.name == dep), None)
                assert dep_comp is not None, f"{c.name} depends on unknown: {dep}"
                assert dep_comp.wave < c.wave, f"{c.name} (wave {c.wave}) depends on {dep} (wave {dep_comp.wave})"

    def test_get_infra_component(self):
        from amzn_cse_telco_autonomous_network_agents_app.agent.agents.anda.config import (
            get_infra_component,
        )

        kro = get_infra_component("kro")
        assert kro is not None
        assert kro.install_method == "helm"
        assert kro.namespace == "kro-system"

    def test_get_infra_component_not_found(self):
        from amzn_cse_telco_autonomous_network_agents_app.agent.agents.anda.config import (
            get_infra_component,
        )

        assert get_infra_component("nonexistent") is None


class TestGetMissingInfrastructure:
    """Tests for get_missing_infrastructure()."""

    @patch("amzn_cse_telco_autonomous_network_agents_app.agent.core.executor.run_cmd")
    def test_all_healthy(self, mock_run):
        mock_run.return_value = FakeCmdResult(success=True, output="1")
        from amzn_cse_telco_autonomous_network_agents_app.agent.agents.anda.config import (
            get_missing_infrastructure,
        )

        missing = get_missing_infrastructure()
        assert missing == []

    @patch("amzn_cse_telco_autonomous_network_agents_app.agent.core.executor.run_cmd")
    def test_all_missing(self, mock_run):
        mock_run.return_value = FakeCmdResult(success=False, output="")
        from amzn_cse_telco_autonomous_network_agents_app.agent.agents.anda.config import (
            get_missing_infrastructure,
        )

        missing = get_missing_infrastructure()
        assert len(missing) >= 4

    @patch("amzn_cse_telco_autonomous_network_agents_app.agent.core.executor.run_cmd")
    def test_partial_missing(self, mock_run):
        def side_effect(cmd, **kwargs):
            if "kro-controller" in cmd:
                return FakeCmdResult(success=True, output="1")
            return FakeCmdResult(success=False, output="")

        mock_run.side_effect = side_effect
        from amzn_cse_telco_autonomous_network_agents_app.agent.agents.anda.config import (
            get_missing_infrastructure,
        )

        missing = get_missing_infrastructure()
        names = [c.name for c in missing]
        assert "kro" not in names
        assert "tinkerbell-stack" in names


class TestBootstrapOrchestration:
    """Tests for _check_and_bootstrap_infrastructure()."""

    @patch("amzn_cse_telco_autonomous_network_agents_app.agent.agents.anda.orchestrator.get_missing_infrastructure")
    @patch("amzn_cse_telco_autonomous_network_agents_app.agent.agents.anda.orchestrator.run_cmd")
    def test_bootstrap_skipped_when_healthy(self, mock_run, mock_missing):
        mock_missing.return_value = []
        from amzn_cse_telco_autonomous_network_agents_app.agent.agents.anda.orchestrator import (
            _check_and_bootstrap_infrastructure,
        )

        _check_and_bootstrap_infrastructure()
        mock_run.assert_not_called()

    @patch("amzn_cse_telco_autonomous_network_agents_app.agent.core.state.push_activity")
    @patch("amzn_cse_telco_autonomous_network_agents_app.agent.agents.anda.orchestrator.component_is_healthy")
    @patch("amzn_cse_telco_autonomous_network_agents_app.agent.agents.anda.orchestrator.get_missing_infrastructure")
    @patch("amzn_cse_telco_autonomous_network_agents_app.agent.agents.anda.orchestrator.run_cmd")
    def test_bootstrap_deploys_in_wave_order(self, mock_run, mock_missing, mock_healthy, mock_activity):
        from amzn_cse_telco_autonomous_network_agents_app.agent.agents.anda.config import (
            InfraComponent,
        )

        mock_missing.return_value = [
            InfraComponent(name="b", type="infrastructure", install_method="helm", source="chart-b", namespace="ns-b", wave=2, depends_on=["a"]),
            InfraComponent(name="a", type="infrastructure", install_method="helm", source="chart-a", namespace="ns-a", wave=1, depends_on=[]),
        ]
        mock_healthy.return_value = True
        mock_run.return_value = FakeCmdResult(success=True, output="deployed")

        from amzn_cse_telco_autonomous_network_agents_app.agent.agents.anda.orchestrator import (
            _check_and_bootstrap_infrastructure,
        )

        _check_and_bootstrap_infrastructure()

        # Should deploy 'a' before 'b' (wave ordering)
        calls = mock_run.call_args_list
        assert len(calls) == 2
        assert "chart-a" in calls[0][0][0]
        assert "chart-b" in calls[1][0][0]

    @patch("amzn_cse_telco_autonomous_network_agents_app.agent.core.state.push_activity")
    @patch("amzn_cse_telco_autonomous_network_agents_app.agent.agents.anda.orchestrator.component_is_healthy")
    @patch("amzn_cse_telco_autonomous_network_agents_app.agent.agents.anda.orchestrator.get_missing_infrastructure")
    @patch("amzn_cse_telco_autonomous_network_agents_app.agent.agents.anda.orchestrator.run_cmd")
    def test_bootstrap_skips_when_deps_not_met(self, mock_run, mock_missing, mock_healthy, mock_activity):
        from amzn_cse_telco_autonomous_network_agents_app.agent.agents.anda.config import (
            InfraComponent,
        )

        mock_missing.return_value = [
            InfraComponent(name="child", type="infrastructure", install_method="helm", source="chart-child", namespace="ns", wave=2, depends_on=["parent"]),
        ]
        mock_healthy.return_value = False  # parent not healthy
        mock_run.return_value = FakeCmdResult(success=True, output="ok")

        from amzn_cse_telco_autonomous_network_agents_app.agent.agents.anda.orchestrator import (
            _check_and_bootstrap_infrastructure,
        )

        _check_and_bootstrap_infrastructure()

        # Should NOT deploy child since parent dep not met
        mock_run.assert_not_called()

    @patch("amzn_cse_telco_autonomous_network_agents_app.agent.core.state.push_activity")
    @patch("amzn_cse_telco_autonomous_network_agents_app.agent.agents.anda.orchestrator.component_is_healthy")
    @patch("amzn_cse_telco_autonomous_network_agents_app.agent.agents.anda.orchestrator.get_missing_infrastructure")
    @patch("amzn_cse_telco_autonomous_network_agents_app.agent.agents.anda.orchestrator.run_cmd")
    def test_bootstrap_uses_correct_method(self, mock_run, mock_missing, mock_healthy, mock_activity):
        from amzn_cse_telco_autonomous_network_agents_app.agent.agents.anda.config import (
            InfraComponent,
        )

        mock_missing.return_value = [
            InfraComponent(name="helm-comp", type="infrastructure", install_method="helm", source="oci://chart", namespace="ns1", wave=1, depends_on=[]),
            InfraComponent(name="kubectl-comp", type="platform", install_method="kubectl_apply", source="manifest.yaml", namespace="ns2", wave=1, depends_on=[]),
        ]
        mock_healthy.return_value = True
        mock_run.return_value = FakeCmdResult(success=True, output="ok")

        from amzn_cse_telco_autonomous_network_agents_app.agent.agents.anda.orchestrator import (
            _check_and_bootstrap_infrastructure,
        )

        _check_and_bootstrap_infrastructure()

        calls = [c[0][0] for c in mock_run.call_args_list]
        assert any("helm upgrade --install" in c for c in calls)
        assert any("kubectl apply" in c for c in calls)


class TestComponentIsHealthy:
    """Tests for component_is_healthy()."""

    @patch("amzn_cse_telco_autonomous_network_agents_app.agent.agents.anda.orchestrator.run_cmd")
    def test_healthy_component(self, mock_run):
        mock_run.return_value = FakeCmdResult(success=True, output="1")
        from amzn_cse_telco_autonomous_network_agents_app.agent.agents.anda.orchestrator import (
            component_is_healthy,
        )

        assert component_is_healthy("kro") is True

    @patch("amzn_cse_telco_autonomous_network_agents_app.agent.agents.anda.orchestrator.run_cmd")
    def test_unhealthy_component(self, mock_run):
        mock_run.return_value = FakeCmdResult(success=False, output="")
        from amzn_cse_telco_autonomous_network_agents_app.agent.agents.anda.orchestrator import (
            component_is_healthy,
        )

        assert component_is_healthy("kro") is False

    def test_unknown_component_is_healthy(self):
        from amzn_cse_telco_autonomous_network_agents_app.agent.agents.anda.orchestrator import (
            component_is_healthy,
        )

        assert component_is_healthy("nonexistent") is True
