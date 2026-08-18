# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
"""Boot Configurer — executes pre-boot Redfish steps before Tinkerbell takes over.

Translates a ProvisioningStrategy (from strategy_engine) into actual Redfish
API calls: mount ISO via VirtualMedia, set boot device, power cycle. This is
the boundary between ANPA intelligence and EKS-H's Tinkerbell workflow.

Responsibilities:
  - VirtualMedia Insert/Eject
  - Boot device override (standard Redfish or Dell OEM)
  - Dell RFS (Remote File Share) configuration
  - Power cycle (ForceRestart / ForceOff + On)
  - Execute pre_steps and post_steps from strategy

Does NOT:
  - Stream OS images (Tinkerbell)
  - Install packages or configure OS (Tinkerbell)
  - Register nodes with EKS (Tinkerbell + nodeadm)
"""

from __future__ import annotations

import json
import logging
import os
import shlex
import tempfile
from dataclasses import dataclass

from amzn_cse_telco_autonomous_network_agents_app.agent.agents.anpa.bmc_profiler import (
    BMCProfile,
)
from amzn_cse_telco_autonomous_network_agents_app.agent.agents.anpa.strategy_engine import (
    ProvisioningStrategy,
)
from amzn_cse_telco_autonomous_network_agents_app.agent.core.executor import run_cmd

logger = logging.getLogger(__name__)


@dataclass
class BootResult:
    """Outcome of a boot configuration attempt."""

    success: bool
    strategy_name: str
    steps_completed: list[str]
    failure_step: str = ""
    failure_reason: str = ""
    failure_type: str = ""


class BootConfigurer:
    """Executes Redfish boot configuration steps for a given strategy."""

    def __init__(self, bmc_address: str, profile: BMCProfile, iso_url: str):
        self._bmc = bmc_address
        self._profile = profile
        self._iso_url = iso_url
        self._user = os.getenv("BMC_USERNAME", "root")
        self._passwd = os.getenv("BMC_PASSWORD", "")
        self._timeout = 15

    def execute(self, strategy: ProvisioningStrategy) -> BootResult:
        """Execute the full boot configuration sequence for the given strategy.

        Order:
          1. Run pre_steps (from quirk YAML)
          2. Mount ISO (if not already done by a pre_step)
          3. Set boot device (if not already done by a pre_step)
          4. Power cycle
        """
        completed = []
        pre_actions_done = set()

        for step in strategy.pre_steps:
            action = step.get("action", "")
            params = step.get("params", {})
            try:
                self._dispatch_action(action, params)
                completed.append(action)
                pre_actions_done.add(action)
            except BootError as e:
                return BootResult(
                    success=False,
                    strategy_name=strategy.name,
                    steps_completed=completed,
                    failure_step=action,
                    failure_reason=str(e),
                    failure_type=e.failure_type,
                )

        if (
            "mount_virtual_media" not in pre_actions_done
            and "configure_rfs" not in pre_actions_done
        ):
            try:
                if strategy.mount_method == "virtual_media_cd":
                    self._mount_virtual_media(slot=None)
                    completed.append("mount_virtual_media")
                elif strategy.mount_method == "rfs_network_file":
                    self._configure_rfs(enable=True)
                    completed.append("configure_rfs")
            except BootError as e:
                step_name = (
                    "mount_virtual_media"
                    if strategy.mount_method == "virtual_media_cd"
                    else "configure_rfs"
                )
                return BootResult(
                    success=False,
                    strategy_name=strategy.name,
                    steps_completed=completed,
                    failure_step=step_name,
                    failure_reason=str(e),
                    failure_type=e.failure_type,
                )

        if (
            "set_dell_oem_boot" not in pre_actions_done
            and "set_boot_override" not in pre_actions_done
        ):
            try:
                if strategy.boot_method == "dell_oem_first_boot_device":
                    self._set_dell_oem_boot(device="VCD-DVD")
                    completed.append("set_dell_oem_boot")
                else:
                    self._set_boot_override(target="Cd")
                    completed.append("set_boot_override")
            except BootError as e:
                return BootResult(
                    success=False,
                    strategy_name=strategy.name,
                    steps_completed=completed,
                    failure_step="set_boot_device",
                    failure_reason=str(e),
                    failure_type=e.failure_type,
                )

        try:
            self._power_cycle()
            completed.append("power_cycle")
        except BootError as e:
            return BootResult(
                success=False,
                strategy_name=strategy.name,
                steps_completed=completed,
                failure_step="power_cycle",
                failure_reason=str(e),
                failure_type=e.failure_type,
            )

        logger.info(
            "Boot configured for %s using strategy '%s': %s",
            self._bmc,
            strategy.name,
            completed,
        )
        return BootResult(
            success=True,
            strategy_name=strategy.name,
            steps_completed=completed,
        )

    def cleanup(self, strategy: ProvisioningStrategy) -> None:
        """Execute post_steps (eject media, restore boot device)."""
        for step in strategy.post_steps:
            action = step.get("action", "")
            params = step.get("params", {})
            try:
                self._dispatch_action(action, params)
            except BootError:
                logger.warning(
                    "Post-step '%s' failed for %s (non-fatal)", action, self._bmc
                )

    def _dispatch_action(self, action: str, params: dict) -> None:
        """Route a named action from pre_steps/post_steps to the right method."""
        dispatch = {
            "mount_virtual_media": lambda: self._mount_virtual_media(
                slot=params.get("slot")
            ),
            "eject_virtual_media": lambda: self._eject_virtual_media(
                slot=params.get("slot")
            ),
            "set_dell_oem_boot": lambda: self._set_dell_oem_boot(
                device=params.get("device", "VCD-DVD")
            ),
            "set_boot_override": lambda: self._set_boot_override(
                target=params.get("target", "Cd")
            ),
            "set_bios_boot_order": lambda: self._set_bios_boot_order(
                first_entry=params.get("first_entry", "")
            ),
            "configure_rfs": lambda: self._configure_rfs(
                enable=params.get("enable", True)
            ),
        }
        handler = dispatch.get(action)
        if not handler:
            raise BootError(f"Unknown action: {action}", "UNKNOWN_ACTION")
        handler()

    # ------------------------------------------------------------------
    # Redfish operations
    # ------------------------------------------------------------------

    def _mount_virtual_media(self, slot: str | None = None) -> None:
        """Insert ISO via Redfish VirtualMedia."""
        cd_path = self._find_cd_slot(slot)
        insert_url = f"{cd_path}/Actions/VirtualMedia.InsertMedia"

        status, body = self._post(insert_url, {"Image": self._iso_url})
        if status not in (200, 202, 204):
            raise BootError(
                f"VirtualMedia InsertMedia failed (HTTP {status}): {body}",
                "VIRTUAL_MEDIA_MOUNT_FAILED",
            )
        logger.info("VirtualMedia mounted on %s: %s", self._bmc, self._iso_url)

    def _eject_virtual_media(self, slot: str | None = None) -> None:
        """Eject ISO from VirtualMedia."""
        cd_path = self._find_cd_slot(slot)
        eject_url = f"{cd_path}/Actions/VirtualMedia.EjectMedia"

        status, body = self._post(eject_url, {})
        if status not in (200, 202, 204):
            raise BootError(
                f"VirtualMedia EjectMedia failed (HTTP {status}): {body}",
                "VIRTUAL_MEDIA_EJECT_FAILED",
            )
        logger.info("VirtualMedia ejected on %s", self._bmc)

    def _set_boot_override(self, target: str = "Cd") -> None:
        """Standard Redfish BootSourceOverrideTarget."""
        payload = {
            "Boot": {
                "BootSourceOverrideTarget": target,
                "BootSourceOverrideEnabled": "Once",
            }
        }
        status, body = self._patch(self._profile.system_path, payload)
        if status not in (200, 202, 204):
            raise BootError(
                f"BootSourceOverride PATCH failed (HTTP {status}): {body}",
                "BOOT_OVERRIDE_FAILED",
            )
        logger.info("Boot override set to '%s' on %s", target, self._bmc)

    def _set_dell_oem_boot(self, device: str = "VCD-DVD") -> None:
        """Dell OEM: set ServerBoot.1.FirstBootDevice via DellAttributes."""
        if not self._profile.oem_boot_path:
            raise BootError(
                "Dell OEM boot path not discovered during profiling",
                "OEM_BOOT_PATH_MISSING",
            )
        payload = {"Attributes": {"ServerBoot.1.FirstBootDevice": device}}
        status, body = self._patch(self._profile.oem_boot_path, payload)
        if status not in (200, 202, 204):
            raise BootError(
                f"Dell OEM boot set failed (HTTP {status}): {body}",
                "DELL_OEM_BOOT_FAILED",
            )
        logger.info("Dell OEM FirstBootDevice set to '%s' on %s", device, self._bmc)

    def _set_bios_boot_order(self, first_entry: str) -> None:
        """Set BIOS boot order so CD/NIC is first."""
        if not self._profile.bios_settings_path:
            raise BootError(
                "BIOS settings path not discovered during profiling",
                "BIOS_PATH_MISSING",
            )
        if not first_entry:
            raise BootError(
                "first_entry not specified for boot order", "INVALID_PARAMS"
            )

        payload = {"Attributes": {"SetBootOrderEn": first_entry}}
        status, body = self._patch(self._profile.bios_settings_path, payload)
        if status not in (200, 202, 204):
            raise BootError(
                f"BIOS boot order PATCH failed (HTTP {status}): {body}",
                "BIOS_BOOT_ORDER_FAILED",
            )
        logger.info(
            "BIOS boot order set first_entry='%s' on %s", first_entry, self._bmc
        )

    def _configure_rfs(self, enable: bool = True) -> None:
        """Configure Dell Remote File Share to serve ISO over network."""
        if not self._profile.has_rfs:
            raise BootError("Dell RFS not available on this BMC", "RFS_NOT_AVAILABLE")
        if not self._profile.oem_boot_path:
            raise BootError(
                "OEM boot path missing for RFS config", "OEM_BOOT_PATH_MISSING"
            )

        if enable:
            payload = {
                "Attributes": {
                    "RFS.2.Image": self._iso_url,
                    "RFS.2.MediaAttachState": "Attached",
                }
            }
        else:
            payload = {
                "Attributes": {
                    "RFS.2.Image": "",
                    "RFS.2.MediaAttachState": "Detached",
                }
            }

        status, body = self._patch(self._profile.oem_boot_path, payload)
        if status not in (200, 202, 204):
            raise BootError(
                f"RFS configure failed (HTTP {status}): {body}",
                "RFS_CONFIGURE_FAILED",
            )
        logger.info("Dell RFS %s on %s", "enabled" if enable else "disabled", self._bmc)

    def _power_cycle(self) -> None:
        """ForceRestart the server."""
        reset_path = f"{self._profile.system_path}/Actions/ComputerSystem.Reset"
        status, body = self._post(reset_path, {"ResetType": "ForceRestart"})
        if status not in (200, 202, 204):
            raise BootError(
                f"Power cycle failed (HTTP {status}): {body}",
                "POWER_CYCLE_FAILED",
            )
        logger.info("Power cycle (ForceRestart) issued to %s", self._bmc)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _find_cd_slot(self, slot: str | None) -> str:
        """Find the VirtualMedia CD slot path."""
        if not self._profile.virtual_media_base:
            raise BootError(
                "No VirtualMedia base discovered during profiling",
                "VIRTUAL_MEDIA_NOT_FOUND",
            )

        for vm_slot in self._profile.virtual_media_slots:
            media_types = vm_slot.get("media_types", [])
            slot_id = vm_slot.get("id", "")
            if slot and slot_id == slot:
                return vm_slot["path"]
            if not slot and ("CD" in media_types or "DVD" in media_types):
                return vm_slot["path"]

        if slot:
            raise BootError(
                f"Requested VirtualMedia slot '{slot}' not found on {self._bmc}",
                "VIRTUAL_MEDIA_SLOT_NOT_FOUND",
            )

        if self._profile.virtual_media_slots:
            return self._profile.virtual_media_slots[0]["path"]

        raise BootError(
            f"No suitable VirtualMedia CD slot found on {self._bmc}",
            "VIRTUAL_MEDIA_SLOT_NOT_FOUND",
        )

    def _request(self, method: str, path: str, payload: dict) -> tuple[int, str]:
        """HTTP request to Redfish endpoint using temp netrc file for credentials."""
        url = shlex.quote(f"https://{self._bmc}{path}")
        data = shlex.quote(json.dumps(payload))
        fd, netrc_path = tempfile.mkstemp(prefix="anpa-netrc-")
        try:
            with os.fdopen(fd, "w") as f:
                f.write(
                    f"machine {self._bmc}\nlogin {self._user}\npassword {self._passwd}\n"
                )
            os.chmod(netrc_path, 0o600)
            cmd = (
                f"curl --silent --insecure --max-time {self._timeout} "
                f"--netrc-file {shlex.quote(netrc_path)} "
                f"-X {method} -H 'Content-Type: application/json' "
                f"-d {data} -w '\\n%{{http_code}}' {url}"
            )
            result = run_cmd(cmd, timeout=self._timeout + 5)
        finally:
            try:
                os.unlink(netrc_path)
            except OSError:
                pass
        return self._parse_response(result)

    def _post(self, path: str, payload: dict) -> tuple[int, str]:
        """HTTP POST to Redfish endpoint. Returns (status_code, body)."""
        return self._request("POST", path, payload)

    def _patch(self, path: str, payload: dict) -> tuple[int, str]:
        """HTTP PATCH to Redfish endpoint. Returns (status_code, body)."""
        return self._request("PATCH", path, payload)

    def _parse_response(self, result) -> tuple[int, str]:
        """Extract HTTP status and body from curl output."""
        if not result.success:
            return 0, result.stderr or "curl failed"
        lines = (result.stdout or "").strip().rsplit("\n", 1)
        body = lines[0].strip() if len(lines) > 1 else ""
        code_str = lines[-1].strip() if lines else "0"
        try:
            code = int(code_str)
        except ValueError:
            code = 0
        return code, body


class BootError(Exception):
    """Raised when a boot configuration step fails."""

    def __init__(self, message: str, failure_type: str = "UNKNOWN"):
        super().__init__(message)
        self.failure_type = failure_type
