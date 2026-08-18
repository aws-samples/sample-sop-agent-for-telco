# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
"""Tests for boot_configurer.py — pre-boot Redfish operations."""

from unittest.mock import MagicMock, patch

import pytest

from amzn_cse_telco_autonomous_network_agents_app.agent.agents.anpa.boot_configurer import (
    BootConfigurer,
    BootError,
)
from amzn_cse_telco_autonomous_network_agents_app.agent.agents.anpa.strategy_engine import (
    ProvisioningStrategy,
)


def _make_profile(**kwargs):
    p = MagicMock()
    p.system_path = kwargs.get("system_path", "/redfish/v1/Systems/System.Embedded.1")
    p.manager_path = kwargs.get("manager_path", "/redfish/v1/Managers/iDRAC.Embedded.1")
    p.virtual_media_base = kwargs.get("virtual_media_base", "/redfish/v1/Systems/System.Embedded.1/VirtualMedia")
    p.virtual_media_slots = kwargs.get(
        "virtual_media_slots",
        [
            {
                "path": "/redfish/v1/Systems/System.Embedded.1/VirtualMedia/CD",
                "media_types": ["CD", "DVD"],
                "id": "CD",
            },
        ],
    )
    p.oem_boot_path = kwargs.get(
        "oem_boot_path",
        "/redfish/v1/Managers/iDRAC.Embedded.1/Oem/Dell/DellAttributes/iDRAC.Embedded.1",
    )
    p.bios_settings_path = kwargs.get("bios_settings_path", "/redfish/v1/Systems/System.Embedded.1/Bios/Settings")
    p.has_rfs = kwargs.get("has_rfs", True)
    p.boot_override_writable = kwargs.get("boot_override_writable", False)
    return p


def _make_strategy(**kwargs):
    return ProvisioningStrategy(
        name=kwargs.get("name", "primary"),
        mount_method=kwargs.get("mount_method", "virtual_media_cd"),
        boot_method=kwargs.get("boot_method", "dell_oem_first_boot_device"),
        hookos_variant=kwargs.get("hookos_variant", "patched-ice"),
        pre_steps=kwargs.get("pre_steps", []),
        post_steps=kwargs.get("post_steps", []),
    )


def _mock_run_cmd_success(*args, **kwargs):
    result = MagicMock()
    result.success = True
    result.stdout = '{"Message": "ok"}\n200'
    result.stderr = ""
    return result


def _mock_run_cmd_failure(*args, **kwargs):
    result = MagicMock()
    result.success = True
    result.stdout = '{"error": "denied"}\n403'
    result.stderr = ""
    return result


class TestBootConfigurerExecute:
    @patch("amzn_cse_telco_autonomous_network_agents_app.agent.agents.anpa.boot_configurer.run_cmd")
    @patch.dict("os.environ", {"BMC_USERNAME": "root", "BMC_PASSWORD": "test123"})
    def test_execute_success_default_strategy(self, mock_run_cmd):
        mock_run_cmd.return_value = _mock_run_cmd_success()
        profile = _make_profile()
        strategy = _make_strategy()
        configurer = BootConfigurer("10.0.0.1", profile, "http://proxy:7080/hook.iso")

        result = configurer.execute(strategy)

        assert result.success is True
        assert result.strategy_name == "primary"
        assert "mount_virtual_media" in result.steps_completed
        assert "set_dell_oem_boot" in result.steps_completed
        assert "power_cycle" in result.steps_completed

    @patch("amzn_cse_telco_autonomous_network_agents_app.agent.agents.anpa.boot_configurer.run_cmd")
    @patch.dict("os.environ", {"BMC_USERNAME": "root", "BMC_PASSWORD": "test123"})
    def test_execute_with_pre_steps(self, mock_run_cmd):
        mock_run_cmd.return_value = _mock_run_cmd_success()
        profile = _make_profile()
        strategy = _make_strategy(
            pre_steps=[
                {"action": "set_dell_oem_boot", "params": {"device": "VCD-DVD"}},
                {"action": "mount_virtual_media", "params": {"slot": "CD"}},
            ]
        )
        configurer = BootConfigurer("10.0.0.1", profile, "http://proxy:7080/hook.iso")

        result = configurer.execute(strategy)

        assert result.success is True
        assert result.steps_completed[0] == "set_dell_oem_boot"
        assert result.steps_completed[1] == "mount_virtual_media"
        assert "power_cycle" in result.steps_completed

    @patch("amzn_cse_telco_autonomous_network_agents_app.agent.agents.anpa.boot_configurer.run_cmd")
    @patch.dict("os.environ", {"BMC_USERNAME": "root", "BMC_PASSWORD": "test123"})
    def test_execute_mount_failure(self, mock_run_cmd):
        mock_run_cmd.return_value = _mock_run_cmd_failure()
        profile = _make_profile()
        strategy = _make_strategy()
        configurer = BootConfigurer("10.0.0.1", profile, "http://proxy:7080/hook.iso")

        result = configurer.execute(strategy)

        assert result.success is False
        assert result.failure_step == "mount_virtual_media"
        assert result.failure_type == "VIRTUAL_MEDIA_MOUNT_FAILED"

    @patch("amzn_cse_telco_autonomous_network_agents_app.agent.agents.anpa.boot_configurer.run_cmd")
    @patch.dict("os.environ", {"BMC_USERNAME": "root", "BMC_PASSWORD": "test123"})
    def test_execute_rfs_strategy(self, mock_run_cmd):
        mock_run_cmd.return_value = _mock_run_cmd_success()
        profile = _make_profile()
        strategy = _make_strategy(mount_method="rfs_network_file")
        configurer = BootConfigurer("10.0.0.1", profile, "http://proxy:7080/hook.iso")

        result = configurer.execute(strategy)

        assert result.success is True
        assert "configure_rfs" in result.steps_completed

    @patch("amzn_cse_telco_autonomous_network_agents_app.agent.agents.anpa.boot_configurer.run_cmd")
    @patch.dict("os.environ", {"BMC_USERNAME": "root", "BMC_PASSWORD": "test123"})
    def test_execute_rfs_failure_reports_correct_step(self, mock_run_cmd):
        mock_run_cmd.return_value = _mock_run_cmd_failure()
        profile = _make_profile()
        strategy = _make_strategy(mount_method="rfs_network_file")
        configurer = BootConfigurer("10.0.0.1", profile, "http://proxy:7080/hook.iso")

        result = configurer.execute(strategy)

        assert result.success is False
        assert result.failure_step == "configure_rfs"
        assert result.failure_type == "RFS_CONFIGURE_FAILED"

    @patch("amzn_cse_telco_autonomous_network_agents_app.agent.agents.anpa.boot_configurer.run_cmd")
    @patch.dict("os.environ", {"BMC_USERNAME": "root", "BMC_PASSWORD": "test123"})
    def test_execute_standard_redfish_boot(self, mock_run_cmd):
        mock_run_cmd.return_value = _mock_run_cmd_success()
        profile = _make_profile()
        strategy = _make_strategy(boot_method="standard_redfish_boot_override")
        configurer = BootConfigurer("10.0.0.1", profile, "http://proxy:7080/hook.iso")

        result = configurer.execute(strategy)

        assert result.success is True
        assert "set_boot_override" in result.steps_completed


class TestBootConfigurerCleanup:
    @patch("amzn_cse_telco_autonomous_network_agents_app.agent.agents.anpa.boot_configurer.run_cmd")
    @patch.dict("os.environ", {"BMC_USERNAME": "root", "BMC_PASSWORD": "test123"})
    def test_cleanup_runs_post_steps(self, mock_run_cmd):
        mock_run_cmd.return_value = _mock_run_cmd_success()
        profile = _make_profile()
        strategy = _make_strategy(
            post_steps=[
                {"action": "eject_virtual_media", "params": {"slot": "CD"}},
                {"action": "set_dell_oem_boot", "params": {"device": "Normal"}},
            ]
        )
        configurer = BootConfigurer("10.0.0.1", profile, "http://proxy:7080/hook.iso")

        configurer.cleanup(strategy)

        assert mock_run_cmd.call_count == 2

    @patch("amzn_cse_telco_autonomous_network_agents_app.agent.agents.anpa.boot_configurer.run_cmd")
    @patch.dict("os.environ", {"BMC_USERNAME": "root", "BMC_PASSWORD": "test123"})
    def test_cleanup_continues_on_failure(self, mock_run_cmd):
        mock_run_cmd.return_value = _mock_run_cmd_failure()
        profile = _make_profile()
        strategy = _make_strategy(
            post_steps=[
                {"action": "eject_virtual_media", "params": {"slot": "CD"}},
                {"action": "set_dell_oem_boot", "params": {"device": "Normal"}},
            ]
        )
        configurer = BootConfigurer("10.0.0.1", profile, "http://proxy:7080/hook.iso")

        configurer.cleanup(strategy)

        assert mock_run_cmd.call_count == 2


class TestFindCdSlot:
    @patch.dict("os.environ", {"BMC_USERNAME": "root", "BMC_PASSWORD": ""})
    def test_find_specific_slot(self):
        profile = _make_profile(
            virtual_media_slots=[
                {"path": "/vm/CD", "media_types": ["CD"], "id": "CD"},
                {"path": "/vm/Floppy", "media_types": ["Floppy"], "id": "Floppy"},
            ]
        )
        configurer = BootConfigurer("10.0.0.1", profile, "http://x/hook.iso")
        assert configurer._find_cd_slot("CD") == "/vm/CD"

    @patch.dict("os.environ", {"BMC_USERNAME": "root", "BMC_PASSWORD": ""})
    def test_find_slot_by_media_type(self):
        profile = _make_profile(
            virtual_media_slots=[
                {"path": "/vm/Floppy", "media_types": ["Floppy"], "id": "1"},
                {"path": "/vm/CD", "media_types": ["CD", "DVD"], "id": "2"},
            ]
        )
        configurer = BootConfigurer("10.0.0.1", profile, "http://x/hook.iso")
        assert configurer._find_cd_slot(None) == "/vm/CD"

    @patch.dict("os.environ", {"BMC_USERNAME": "root", "BMC_PASSWORD": ""})
    def test_raises_when_requested_slot_not_found(self):
        profile = _make_profile(
            virtual_media_slots=[
                {"path": "/vm/CD", "media_types": ["CD"], "id": "CD"},
            ]
        )
        configurer = BootConfigurer("10.0.0.1", profile, "http://x/hook.iso")
        with pytest.raises(BootError, match="not found"):
            configurer._find_cd_slot("MISSING")

    @patch.dict("os.environ", {"BMC_USERNAME": "root", "BMC_PASSWORD": ""})
    def test_raises_when_no_vm_base(self):
        profile = _make_profile(virtual_media_base="")
        configurer = BootConfigurer("10.0.0.1", profile, "http://x/hook.iso")
        with pytest.raises(BootError, match="No VirtualMedia base"):
            configurer._find_cd_slot(None)


class TestDispatchAction:
    @patch("amzn_cse_telco_autonomous_network_agents_app.agent.agents.anpa.boot_configurer.run_cmd")
    @patch.dict("os.environ", {"BMC_USERNAME": "root", "BMC_PASSWORD": ""})
    def test_unknown_action_raises(self, mock_run_cmd):
        profile = _make_profile()
        configurer = BootConfigurer("10.0.0.1", profile, "http://x/hook.iso")
        with pytest.raises(BootError, match="Unknown action"):
            configurer._dispatch_action("nonexistent_action", {})
