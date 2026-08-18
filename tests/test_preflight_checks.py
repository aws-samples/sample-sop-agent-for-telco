# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
"""Tests for the ANPA preflight_checks module.

Covers hardware-registration + BMC-reachability validation the state machine
runs before advancing a request to Provisioning. run_cmd is patched at the
module preflight lives in.
"""

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from amzn_cse_telco_autonomous_network_agents_app.agent.agents.anpa import (
    preflight_checks,
)


def _r(stdout="", returncode=0, stderr=""):
    return SimpleNamespace(
        stdout=stdout, stderr=stderr, returncode=returncode, success=returncode == 0
    )


class TestPreflightChecks:
    @patch.object(preflight_checks, "run_cmd")
    def test_missing_required_field_raises(self, mock_run):
        # spec lacks osArchive/gateway/etc.
        with pytest.raises(RuntimeError, match="is required"):
            preflight_checks._run_preflight("req", "ns", {"hostname": "n1"})
        mock_run.assert_not_called()

    @patch.object(preflight_checks, "run_cmd")
    def test_missing_hardware_inventory_raises(self, mock_run):
        mock_run.return_value = _r(stdout="")  # CR not found
        spec = {
            "hostname": "n1",
            "osArchive": "x",
            "gateway": "g",
            "netmaskCIDR": "24",
            "ip": "1.2.3.4",
        }
        with pytest.raises(RuntimeError, match="not found"):
            preflight_checks._run_preflight("req", "ns", spec)

    @patch.object(preflight_checks, "run_cmd")
    def test_malformed_inventory_json_raises(self, mock_run):
        # A HardwareInventory CR whose JSON won't parse must fail loud, not
        # silently skip the BMC probe and report "preflight passed". Only the
        # single kubectl-get ran (no BMC probe) before the raise.
        mock_run.return_value = _r(stdout="{not valid json")
        spec = {
            "hostname": "n1",
            "osArchive": "x",
            "gateway": "g",
            "netmaskCIDR": "24",
            "ip": "1.2.3.4",
        }
        with pytest.raises(RuntimeError, match="unparseable JSON"):
            preflight_checks._run_preflight("req", "ns", spec)
        assert mock_run.call_count == 1

    @patch.object(preflight_checks, "run_cmd")
    def test_missing_bmc_address_raises(self, mock_run):
        # Valid inventory JSON but no bmcAddress: preflight cannot verify BMC
        # reachability, so it must raise rather than skip and report passed.
        mock_run.return_value = _r(stdout='{"spec": {}}')
        spec = {
            "hostname": "n1",
            "osArchive": "x",
            "gateway": "g",
            "netmaskCIDR": "24",
            "ip": "1.2.3.4",
        }
        with pytest.raises(RuntimeError, match="no bmcAddress"):
            preflight_checks._run_preflight("req", "ns", spec)
        # Only the kubectl-get ran; no BMC probe was attempted.
        assert mock_run.call_count == 1

    @patch.object(preflight_checks, "run_cmd")
    def test_non_object_inventory_json_raises(self, mock_run):
        # Valid JSON that isn't an object (e.g. a list) must fail loud with a
        # clear message rather than leaking an AttributeError from .get().
        mock_run.return_value = _r(stdout="[]")
        spec = {
            "hostname": "n1",
            "osArchive": "x",
            "gateway": "g",
            "netmaskCIDR": "24",
            "ip": "1.2.3.4",
        }
        with pytest.raises(RuntimeError, match="not a JSON object"):
            preflight_checks._run_preflight("req", "ns", spec)
        assert mock_run.call_count == 1

    @patch.object(preflight_checks, "run_cmd")
    def test_unreachable_bmc_raises(self, mock_run):
        # Inventory has a bmcAddress but the curl probe returns a non-200/401
        # status -> BMC is unreachable -> raise.
        mock_run.side_effect = [
            _r(stdout='{"spec": {"bmcAddress": "10.0.0.5"}}'),
            _r(stdout="500"),
        ]
        spec = {
            "hostname": "n1",
            "osArchive": "x",
            "gateway": "g",
            "netmaskCIDR": "24",
            "ip": "1.2.3.4",
        }
        with pytest.raises(RuntimeError, match="not reachable"):
            preflight_checks._run_preflight("req", "ns", spec)
        assert mock_run.call_count == 2

    @patch.object(preflight_checks, "run_cmd")
    def test_multi_node_early_abort_on_first_bad_node(self, mock_run):
        # A bad first node must abort the whole preflight — the second node's
        # inventory/probe must never run.
        mock_run.return_value = _r(stdout="")  # kubectl get: CR not found
        spec = {
            "osArchive": "x",
            "gateway": "g",
            "netmaskCIDR": "24",
            "ip": "1.2.3.4",
            "nodes": [
                {"hostname": "n1"},
                {"hostname": "n2"},
            ],
        }
        with pytest.raises(RuntimeError, match="not found"):
            preflight_checks._run_preflight("req", "ns", spec)
        # Only node n1's kubectl-get ran; n2 was never reached.
        assert mock_run.call_count == 1

    @patch.object(preflight_checks, "run_cmd")
    def test_reachable_bmc_passes(self, mock_run):
        # Valid inventory + reachable BMC (HTTP 200) -> preflight passes.
        # First call: kubectl get returns inventory JSON with a bmcAddress.
        # Second call: curl probe returns 200.
        mock_run.side_effect = [
            _r(stdout='{"spec": {"bmcAddress": "10.0.0.5"}}'),
            _r(stdout="200"),
        ]
        spec = {
            "hostname": "n1",
            "osArchive": "x",
            "gateway": "g",
            "netmaskCIDR": "24",
            "ip": "1.2.3.4",
        }
        assert preflight_checks._run_preflight("req", "ns", spec) is None
        assert mock_run.call_count == 2
