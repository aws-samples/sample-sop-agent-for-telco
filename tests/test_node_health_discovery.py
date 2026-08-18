# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
"""Tests for the ANPA node_health_discovery module.

Covers the periodic-cadence tasks that run independent of the per-request state
machine: cluster node-health inspection + Redfish subnet discovery. run_cmd is
patched at the module the tasks live in.
"""

from types import SimpleNamespace
from unittest.mock import patch

from amzn_cse_telco_autonomous_network_agents_app.agent.agents.anpa import (
    node_health_discovery,
)


def _r(stdout="", returncode=0, stderr=""):
    return SimpleNamespace(stdout=stdout, stderr=stderr, returncode=returncode, success=returncode == 0)


class TestNodeHealthDiscovery:
    @patch.object(node_health_discovery, "run_cmd")
    def test_health_check_all_ready_no_warn(self, mock_run):
        mock_run.return_value = _r(stdout='{"items":[{"metadata":{"name":"n1"},"status":{"conditions":[{"type":"Ready","status":"True"}]}}]}')
        # Should not raise; returns None
        assert node_health_discovery._check_node_health() is None

    @patch.object(node_health_discovery, "run_cmd")
    def test_health_check_handles_kubectl_failure(self, mock_run):
        mock_run.return_value = _r(returncode=1, stderr="boom")
        assert node_health_discovery._check_node_health() is None

    def test_discovery_no_subnets_is_noop(self):
        fake_cfg = SimpleNamespace(tinkerbell_namespace="tink", nodes=[])
        with patch.object(node_health_discovery, "load_config", return_value=fake_cfg):
            # No BMC IPs -> returns without scanning; must not raise.
            assert node_health_discovery._run_discovery() is None
