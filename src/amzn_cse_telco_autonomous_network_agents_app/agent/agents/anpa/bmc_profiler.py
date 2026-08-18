# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
"""BMC Profiler — deep Redfish capability discovery for bare-metal provisioning.

Probes a BMC's Redfish API tree to discover vendor-specific capabilities,
VirtualMedia paths, boot method support, OEM extensions, and NIC info.
Used by the reconciler during VALIDATING phase to select the right
provisioning strategy before emitting BareMetalProvision CRs.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field


logger = logging.getLogger(__name__)


@dataclass
class BMCProfile:
    """Full capability map of a BMC discovered via Redfish."""

    # Identity
    vendor: str = ""
    model: str = ""
    firmware_version: str = ""
    bmc_type: str = ""  # idrac | ilo | generic-redfish
    oem_namespace: str = ""  # Dell | Hpe | ""

    # Paths (discovered dynamically, NOT hardcoded)
    system_path: str = ""
    manager_path: str = ""
    virtual_media_base: str = ""

    # Boot capabilities
    boot_override_writable: bool = True
    boot_targets_allowed: list = field(default_factory=list)
    has_oem_boot: bool = False
    oem_boot_path: str = ""
    bios_settings_path: str = ""

    # VirtualMedia
    virtual_media_slots: list = field(default_factory=list)
    has_rfs: bool = False

    # Network
    nic_models: list = field(default_factory=list)
    requires_custom_hookos: bool = False

    # Raw data for debugging
    redfish_version: str = ""


def profile_bmc(
    bmc_address: str,
    username: str = "",
    password: str = "",
    timeout: int = 10,
) -> BMCProfile:
    """Deep-profile a BMC via Redfish. Returns BMCProfile with full capability map.

    Args:
        bmc_address: IP or hostname of the BMC.
        username: Redfish auth username. Defaults to BMC_USERNAME env var.
        password: Redfish auth password. Defaults to BMC_PASSWORD env var.
        timeout: Per-request timeout in seconds.

    Returns:
        BMCProfile with discovered capabilities. On failure, returns a
        partially-filled profile with whatever was discoverable.
    """
    user = username or os.getenv("BMC_USERNAME", "root")
    passwd = password or os.getenv("BMC_PASSWORD", "")
    profile = BMCProfile()

    from amzn_cse_telco_autonomous_network_agents_app.agent.util.bmc import curl_bmc

    def _get(path: str) -> dict | None:
        result = curl_bmc(f"https://{bmc_address}{path}", user, passwd, timeout=timeout)
        if not result.returncode == 0:
            return None
        try:
            return json.loads(result.stdout)
        except (json.JSONDecodeError, TypeError):
            return None

    def _patch_test(path: str, payload: dict) -> int:
        """PATCH with payload and return HTTP status code."""
        payload_json = json.dumps(payload)
        result = curl_bmc(
            f"https://{bmc_address}{path}",
            user,
            passwd,
            method="PATCH",
            data=payload_json,
            extra_args=[
                "-H",
                "Content-Type: application/json",
                "-w",
                "%{http_code}",
                "-o",
                "/dev/null",
            ],
            timeout=timeout,
        )
        if not result.returncode == 0:
            return 0
        try:
            return int(result.stdout.strip().replace("'", ""))
        except (ValueError, TypeError):
            return 0

    # 1. Service root
    root = _get("/redfish/v1")
    if not root:
        logger.warning("BMC %s: Redfish service root unreachable", bmc_address)
        return profile

    profile.redfish_version = root.get("RedfishVersion", "")
    oem = root.get("Oem", {})
    if "Dell" in oem:
        profile.oem_namespace = "Dell"
        profile.bmc_type = "idrac"
    elif "Hpe" in oem:
        profile.oem_namespace = "Hpe"
        profile.bmc_type = "ilo"
    else:
        profile.bmc_type = "generic-redfish"

    # 2. Systems collection → discover system path
    systems = _get("/redfish/v1/Systems")
    if systems and systems.get("Members"):
        profile.system_path = systems["Members"][0].get("@odata.id", "")

    if not profile.system_path:
        profile.system_path = "/redfish/v1/Systems/System.Embedded.1"

    # 3. System details
    system = _get(profile.system_path)
    if system:
        profile.model = system.get("Model", "")
        profile.vendor = system.get("Manufacturer", "")

        boot = system.get("Boot", {})
        profile.boot_targets_allowed = boot.get(
            "BootSourceOverrideTarget@Redfish.AllowableValues", []
        )

        # 4. Test boot override writability (no-op PATCH with current value)
        current_target = boot.get("BootSourceOverrideTarget", "None")
        status = _patch_test(
            profile.system_path,
            {"Boot": {"BootSourceOverrideTarget": current_target}},
        )
        if status in (400, 405):
            profile.boot_override_writable = False
            logger.info("BMC %s: BootSourceOverride is read-only", bmc_address)

    # 5. Managers → discover manager path + firmware
    managers = _get("/redfish/v1/Managers")
    if managers and managers.get("Members"):
        profile.manager_path = managers["Members"][0].get("@odata.id", "")

    if profile.manager_path:
        manager = _get(profile.manager_path)
        if manager:
            profile.firmware_version = manager.get("FirmwareVersion", "")
            mgr_oem = manager.get("Oem", {})
            if "Dell" in mgr_oem:
                profile.has_oem_boot = True
                manager_id = profile.manager_path.rstrip("/").split("/")[-1]
                profile.oem_boot_path = (
                    f"{profile.manager_path}/Oem/Dell/DellAttributes/{manager_id}"
                )

    # 6. BIOS settings path
    if profile.system_path:
        bios = _get(f"{profile.system_path}/Bios")
        if bios:
            settings_link = bios.get("@Redfish.Settings", {}).get(
                "SettingsObject", {}
            ).get("@odata.id", "")
            if settings_link:
                profile.bios_settings_path = settings_link

    # 7. VirtualMedia discovery (try Systems first, then Managers)
    vm_path = f"{profile.system_path}/VirtualMedia"
    vm_collection = _get(vm_path)
    if vm_collection and vm_collection.get("Members"):
        profile.virtual_media_base = vm_path
    elif profile.manager_path:
        vm_path = f"{profile.manager_path}/VirtualMedia"
        vm_collection = _get(vm_path)
        if vm_collection and vm_collection.get("Members"):
            profile.virtual_media_base = vm_path

    if vm_collection and vm_collection.get("Members"):
        for member in vm_collection["Members"]:
            member_path = member.get("@odata.id", "")
            vm_detail = _get(member_path)
            if vm_detail:
                profile.virtual_media_slots.append({
                    "path": member_path,
                    "media_types": vm_detail.get("MediaTypes", []),
                    "inserted": vm_detail.get("Inserted", False),
                    "id": vm_detail.get("Id", ""),
                })

    # 8. Check for Dell RFS (Remote File Share)
    if profile.oem_namespace == "Dell" and profile.manager_path:
        dell_attrs = _get(profile.oem_boot_path) if profile.oem_boot_path else None
        if dell_attrs:
            attrs = dell_attrs.get("Attributes", {})
            if any(k.startswith("RFS.") for k in attrs):
                profile.has_rfs = True

    # 9. NIC discovery
    if profile.system_path:
        nics = _get(f"{profile.system_path}/EthernetInterfaces")
        if nics and nics.get("Members"):
            for nic_ref in nics["Members"][:4]:  # limit to 4 NICs
                nic_path = nic_ref.get("@odata.id", "")
                nic_detail = _get(nic_path)
                if nic_detail:
                    nic_info = {
                        "id": nic_detail.get("Id", ""),
                        "mac": nic_detail.get("MACAddress", ""),
                        "speed_mbps": nic_detail.get("SpeedMbps"),
                    }
                    # Check for Intel E825-C (needs custom ice driver in HookOS)
                    description = nic_detail.get("Description", "") + nic_detail.get("Name", "")
                    if "E825" in description or "E810" in description:
                        profile.requires_custom_hookos = True
                        nic_info["requires_driver"] = "ice"
                    profile.nic_models.append(nic_info)

    logger.info(
        "BMC %s profiled: vendor=%s model=%s fw=%s boot_writable=%s vm_base=%s oem=%s",
        bmc_address,
        profile.vendor,
        profile.model,
        profile.firmware_version,
        profile.boot_override_writable,
        profile.virtual_media_base,
        profile.oem_namespace,
    )
    return profile
