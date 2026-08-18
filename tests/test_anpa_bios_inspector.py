# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Tests for ANPA bios_inspector — Phase 2.1 read-only Redfish primitives."""

import json
from dataclasses import dataclass
from unittest.mock import patch

import pytest

from amzn_cse_telco_autonomous_network_agents_app.agent.agents.anpa import bios_inspector


@dataclass
class FakeR:
    stdout: str = ""
    stderr: str = ""
    returncode: int = 0
    @property
    def success(self) -> bool: return self.returncode == 0


class TestBiosAttributes:
    @patch("amzn_cse_telco_autonomous_network_agents_app.agent.util.bmc.curl_bmc")
    def test_returns_attributes_map(self, mock_run, monkeypatch):
        monkeypatch.setenv("BMC_PASSWORD", "calvin")
        mock_run.return_value = FakeR(stdout=json.dumps({
            "Attributes": {"BootMode": "Uefi", "SriovGlobalEnable": "Enabled"}
        }))
        attrs = bios_inspector.get_bios_attributes("192.168.30.10")
        assert attrs["BootMode"] == "Uefi"
        assert attrs["SriovGlobalEnable"] == "Enabled"

    @patch("amzn_cse_telco_autonomous_network_agents_app.agent.util.bmc.curl_bmc")
    def test_curl_failure_returns_empty(self, mock_run):
        mock_run.return_value = FakeR(returncode=7)
        assert bios_inspector.get_bios_attributes("10.0.0.1") == {}

    @patch("amzn_cse_telco_autonomous_network_agents_app.agent.util.bmc.curl_bmc")
    def test_explicit_creds_passed_to_helper(self, mock_run):
        mock_run.return_value = FakeR(stdout="{}")
        bios_inspector.get_bios_attributes("10.0.0.1", username="admin", password="pw1")
        # Creds go to the hardened helper as args, not interpolated into a command.
        args, _ = mock_run.call_args
        assert "admin" in args and "pw1" in args
        assert args[0].startswith("https://10.0.0.1")

    @patch("amzn_cse_telco_autonomous_network_agents_app.agent.util.bmc.curl_bmc")
    def test_env_creds_default(self, mock_run, monkeypatch):
        monkeypatch.setenv("BMC_USERNAME", "envuser")
        monkeypatch.setenv("BMC_PASSWORD", "envpw")
        mock_run.return_value = FakeR(stdout="{}")
        bios_inspector.get_bios_attributes("10.0.0.1")
        args, _ = mock_run.call_args
        assert "envuser" in args and "envpw" in args


class TestFirmwareInventory:
    @patch("amzn_cse_telco_autonomous_network_agents_app.agent.util.bmc.curl_bmc")
    def test_walks_collection(self, mock_run):
        responses = [
            FakeR(stdout=json.dumps({
                "Members": [
                    {"@odata.id": "/redfish/v1/UpdateService/FirmwareInventory/A"},
                    {"@odata.id": "/redfish/v1/UpdateService/FirmwareInventory/B"},
                ]
            })),
            FakeR(stdout=json.dumps({"Id": "A", "Name": "BIOS", "Version": "2.10", "Updateable": True})),
            FakeR(stdout=json.dumps({"Id": "B", "Name": "Intel E810", "Version": "4.30", "Updateable": True})),
        ]
        mock_run.side_effect = responses
        out = bios_inspector.get_firmware_inventory("10.0.0.1", username="u", password="p")
        assert len(out) == 2
        names = {item["name"] for item in out}
        assert "BIOS" in names and "Intel E810" in names

    @patch("amzn_cse_telco_autonomous_network_agents_app.agent.util.bmc.curl_bmc")
    def test_skips_failed_members(self, mock_run):
        mock_run.side_effect = [
            FakeR(stdout=json.dumps({
                "Members": [
                    {"@odata.id": "/a"},
                    {"@odata.id": "/b"},
                ]
            })),
            FakeR(returncode=7),  # member fetch fails
            FakeR(stdout=json.dumps({"Id": "B", "Name": "OK"})),
        ]
        out = bios_inspector.get_firmware_inventory("10.0.0.1", username="u", password="p")
        assert len(out) == 1


class TestProcessorTopology:
    @patch("amzn_cse_telco_autonomous_network_agents_app.agent.util.bmc.curl_bmc")
    def test_aggregates_two_sockets(self, mock_run):
        mock_run.side_effect = [
            FakeR(stdout=json.dumps({
                "Members": [{"@odata.id": "/cpu1"}, {"@odata.id": "/cpu2"}, {"@odata.id": "/gpu"}]
            })),
            FakeR(stdout=json.dumps({"ProcessorType": "CPU", "TotalCores": 32, "TotalThreads": 64, "Model": "Xeon"})),
            FakeR(stdout=json.dumps({"ProcessorType": "CPU", "TotalCores": 32, "TotalThreads": 64, "Model": "Xeon"})),
            FakeR(stdout=json.dumps({"ProcessorType": "GPU"})),  # filtered out
        ]
        topo = bios_inspector.get_processor_topology("10.0.0.1", username="u", password="p")
        assert topo["sockets"] == 2
        assert topo["total_cores"] == 64
        assert topo["total_threads"] == 128
        assert topo["models"] == ["Xeon"]
