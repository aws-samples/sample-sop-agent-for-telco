# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
"""Tests for bmc_profiler — BMC capability discovery via Redfish."""

import json
from unittest.mock import MagicMock, patch

from amzn_cse_telco_autonomous_network_agents_app.agent.agents.anpa.bmc_profiler import (
    BMCProfile,
    profile_bmc,
)


def _cmd_result(stdout="", returncode=0):
    r = MagicMock()
    r.stdout = stdout
    r.returncode = returncode
    r.success = returncode == 0
    r.output = stdout
    return r


class TestBMCProfile:
    def test_default_values(self):
        p = BMCProfile()
        assert p.boot_override_writable is True
        assert p.vendor == ""
        assert p.nic_models == []

    def test_fields_assignable(self):
        p = BMCProfile(vendor="Dell", model="XR8720t", boot_override_writable=False)
        assert p.vendor == "Dell"
        assert not p.boot_override_writable


class TestProfileBmc:
    @patch("amzn_cse_telco_autonomous_network_agents_app.agent.util.bmc.curl_bmc")
    def test_unreachable_bmc_returns_empty_profile(self, mock_cmd):
        mock_cmd.return_value = _cmd_result(returncode=-1)
        profile = profile_bmc("10.0.0.1", "root", "pass")
        assert profile.vendor == ""
        assert profile.model == ""

    @patch("amzn_cse_telco_autonomous_network_agents_app.agent.util.bmc.curl_bmc")
    def test_dell_idrac_detected(self, mock_cmd):
        responses = {
            "/redfish/v1": json.dumps({"RedfishVersion": "1.17", "Oem": {"Dell": {}}}),
            "/redfish/v1/Systems": json.dumps({"Members": [{"@odata.id": "/redfish/v1/Systems/System.Embedded.1"}]}),
            "/redfish/v1/Systems/System.Embedded.1": json.dumps({
                "Model": "PowerEdge XR8720t",
                "Manufacturer": "Dell Inc.",
                "Boot": {
                    "BootSourceOverrideTarget": "None",
                    "BootSourceOverrideTarget@Redfish.AllowableValues": ["None", "Cd", "Pxe"],
                },
            }),
            "/redfish/v1/Managers": json.dumps({"Members": [{"@odata.id": "/redfish/v1/Managers/iDRAC.Embedded.1"}]}),
            "/redfish/v1/Managers/iDRAC.Embedded.1": json.dumps({
                "FirmwareVersion": "7.10.30.00",
                "Oem": {"Dell": {}},
            }),
        }

        def side_effect(url, username=None, password=None, *, method=None, **kwargs):
            if method == "PATCH":
                return _cmd_result(stdout="400")
            for path, body in sorted(responses.items(), key=lambda x: -len(x[0])):
                if url.endswith(path):
                    return _cmd_result(stdout=body)
            return _cmd_result(stdout="{}", returncode=0)

        mock_cmd.side_effect = side_effect

        profile = profile_bmc("10.0.0.1", "root", "pass")
        assert profile.vendor == "Dell Inc."
        assert profile.model == "PowerEdge XR8720t"
        assert profile.bmc_type == "idrac"
        assert profile.oem_namespace == "Dell"
        assert profile.boot_override_writable is False
        assert profile.firmware_version == "7.10.30.00"

    @patch("amzn_cse_telco_autonomous_network_agents_app.agent.util.bmc.curl_bmc")
    def test_standard_bmc_boot_writable(self, mock_cmd):
        responses = {
            "/redfish/v1": json.dumps({"RedfishVersion": "1.13", "Oem": {}}),
            "/redfish/v1/Systems": json.dumps({"Members": [{"@odata.id": "/redfish/v1/Systems/1"}]}),
            "/redfish/v1/Systems/1": json.dumps({
                "Model": "ProLiant DL380",
                "Manufacturer": "HPE",
                "Boot": {"BootSourceOverrideTarget": "None"},
            }),
            "/redfish/v1/Managers": json.dumps({"Members": []}),
        }

        def side_effect(url, username=None, password=None, *, method=None, **kwargs):
            if method == "PATCH":
                return _cmd_result(stdout="200")
            for path, body in sorted(responses.items(), key=lambda x: -len(x[0])):
                if url.endswith(path):
                    return _cmd_result(stdout=body)
            return _cmd_result(stdout="{}", returncode=0)

        mock_cmd.side_effect = side_effect

        profile = profile_bmc("10.0.0.2", "admin", "pass")
        assert profile.boot_override_writable is True
        assert profile.bmc_type == "generic-redfish"

    @patch("amzn_cse_telco_autonomous_network_agents_app.agent.util.bmc.curl_bmc")
    def test_nic_detection_intel_e825(self, mock_cmd):
        responses = {
            "/redfish/v1": json.dumps({"RedfishVersion": "1.17", "Oem": {"Dell": {}}}),
            "/redfish/v1/Systems": json.dumps({"Members": [{"@odata.id": "/redfish/v1/Systems/System.Embedded.1"}]}),
            "/redfish/v1/Systems/System.Embedded.1": json.dumps({
                "Model": "XR8720t", "Manufacturer": "Dell",
                "Boot": {"BootSourceOverrideTarget": "None"},
            }),
            "/redfish/v1/Managers": json.dumps({"Members": []}),
            "/redfish/v1/Systems/System.Embedded.1/EthernetInterfaces": json.dumps({
                "Members": [{"@odata.id": "/redfish/v1/Systems/System.Embedded.1/EthernetInterfaces/NIC.Slot.3-1"}],
            }),
            "/redfish/v1/Systems/System.Embedded.1/EthernetInterfaces/NIC.Slot.3-1": json.dumps({
                "Id": "NIC.Slot.3-1",
                "MACAddress": "d0:37:45:39:94:5a",
                "Description": "Intel E825-C 100GbE",
                "SpeedMbps": 100000,
            }),
        }

        def side_effect(url, username=None, password=None, *, method=None, **kwargs):
            if method == "PATCH":
                return _cmd_result(stdout="400")
            for path, body in sorted(responses.items(), key=lambda x: -len(x[0])):
                if url.endswith(path):
                    return _cmd_result(stdout=body)
            return _cmd_result(stdout="{}", returncode=0)

        mock_cmd.side_effect = side_effect

        profile = profile_bmc("10.0.0.1", "root", "pass")
        assert profile.requires_custom_hookos is True
        assert len(profile.nic_models) == 1
        assert profile.nic_models[0]["requires_driver"] == "ice"
