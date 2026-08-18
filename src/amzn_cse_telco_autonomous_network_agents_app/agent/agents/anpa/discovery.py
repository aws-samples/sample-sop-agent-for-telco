# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""
Hardware discovery module for ANPA (Autonomous Node Provisioning Agent).

Scans subnets for Redfish-capable BMCs, retrieves hardware inventory,
creates HardwareInventory CRs, and reconciles known vs. discovered servers.
"""

from __future__ import annotations

import ipaddress
import json
import logging
import os
import tempfile
from typing import Any

from amzn_cse_telco_autonomous_network_agents_app.agent.core.executor import run_cmd

logger = logging.getLogger(__name__)


def scan_redfish_endpoints(
    subnet_cidr: str,
    username: str | None = None,
    password: str | None = None,
) -> list[dict]:
    """Scan a subnet for Redfish-capable BMCs.

    Iterates over every host address in *subnet_cidr* and probes port 443
    (HTTPS) at /redfish/v1 with a short curl timeout.  For each responding
    host the full hardware details are fetched via :func:`get_hardware_info`
    and appended to the result list.

    Note:
        A production implementation would use async I/O or nmap for speed.
        This sequential version is intentionally simple and easy to test.

    Args:
        subnet_cidr: CIDR notation subnet to scan, e.g. ``"192.168.1.0/24"``.
        username:    BMC username. Defaults to env ``BMC_USERNAME`` or ``"root"``.
        password:    BMC password. Defaults to env ``BMC_PASSWORD`` or empty.

    Returns:
        List of hardware-info dicts as returned by :func:`get_hardware_info`.
        Each dict contains at least ``ip``, ``model``, ``serial``,
        ``cpu_count``, and ``memory_gb`` keys.
    """
    if username is None:
        username = os.environ.get("BMC_USERNAME", "root")
    if password is None:
        password = os.environ.get("BMC_PASSWORD", "")
    network = ipaddress.ip_network(subnet_cidr, strict=False)
    discovered: list[dict] = []

    for host in network.hosts():
        ip = str(host)
        logger.debug("Probing %s for Redfish endpoint", ip)

        from amzn_cse_telco_autonomous_network_agents_app.agent.util.bmc import curl_bmc

        result = curl_bmc(
            f"https://{ip}/redfish/v1", username, password, timeout=5, max_time=3
        )

        if result.returncode != 0:
            logger.debug("No Redfish response from %s (rc=%d)", ip, result.returncode)
            continue

        # Quick sanity-check: response should contain the Redfish version marker
        if "RedfishVersion" not in (result.stdout or ""):
            logger.debug("Unexpected response from %s; skipping", ip)
            continue

        logger.info("Redfish endpoint discovered at %s", ip)
        try:
            hw_info = get_hardware_info(
                bmc_address=ip,
                username=username,
                password=password,
            )
            # Flatten to the compact summary format expected by callers
            summary = {
                "ip": ip,
                "model": hw_info.get("model", "unknown"),
                "serial": hw_info.get("serial", "unknown"),
                "system_uuid": hw_info.get("system_uuid", ""),
                "cpu_count": hw_info.get("cpu_cores", 0),
                "memory_gb": hw_info.get("memory_gib", 0),
            }
            discovered.append(summary)
        except Exception as exc:  # pylint: disable=broad-except
            logger.warning("Failed to fetch hardware info from %s: %s", ip, exc)

    logger.info(
        "Redfish scan of %s complete: %d BMC(s) found", subnet_cidr, len(discovered)
    )
    return discovered


def get_hardware_info(bmc_address: str, username: str, password: str) -> dict:
    """Retrieve detailed hardware information from a Redfish BMC.

    Queries two Redfish endpoints:

    * ``/redfish/v1/Systems/System.Embedded.1`` – CPU / memory / NIC data.
    * ``/redfish/v1/Chassis/System.Embedded.1``  – model / serial number.

    Args:
        bmc_address: Hostname or IP address of the BMC.
        username:    Redfish username.
        password:    Redfish password.

    Returns:
        Structured dict::

            {
                "hostname":     str,
                "bmc_address":  str,
                "model":        str,
                "serial":       str,
                "cpu_cores":    int,
                "memory_gib":   int,
                "interfaces": [
                    {"name": str, "mac": str, "speed": int},
                    ...
                ],
            }

    Raises:
        RuntimeError: If any Redfish query fails (non-zero exit code).
    """
    from amzn_cse_telco_autonomous_network_agents_app.agent.util.bmc import curl_bmc

    base_url = f"https://{bmc_address}"

    def _redfish_get(path: str) -> dict[str, Any]:
        result = curl_bmc(f"{base_url}{path}", username, password, timeout=15)
        if result.returncode != 0:
            raise RuntimeError(
                f"Redfish GET {path} failed (rc={result.returncode}): {result.stderr}"
            )
        return json.loads(result.stdout or "{}")

    # --- System endpoint ---------------------------------------------------
    system = _redfish_get("/redfish/v1/Systems/System.Embedded.1")

    hostname: str = system.get("HostName") or system.get("Id", bmc_address)

    # SMBIOS UUID — the canonical identifier that links a BMC to its eventual
    # K8s node (matches node.status.nodeInfo.systemUUID exactly).
    system_uuid: str = (system.get("UUID") or "").strip()

    # CPU
    cpu_summary = system.get("ProcessorSummary", {})
    cpu_cores: int = cpu_summary.get("LogicalProcessorCount") or cpu_summary.get(
        "Count", 0
    )
    cpu_model: str = cpu_summary.get("Model", "unknown")

    # Memory  (Redfish reports in MiB → convert to GiB)
    mem_summary = system.get("MemorySummary", {})
    memory_gib: int = int(
        (mem_summary.get("TotalSystemMemoryGiB") or 0)
        or (mem_summary.get("TotalSystemMemoryMiB", 0) / 1024)
    )

    # NICs
    interfaces: list[dict] = []
    ethernet_interfaces = system.get("EthernetInterfaces", {})
    nic_collection_path: str | None = None
    if isinstance(ethernet_interfaces, dict):
        nic_collection_path = ethernet_interfaces.get("@odata.id")

    if nic_collection_path:
        try:
            nic_collection = _redfish_get(nic_collection_path)
            for member in nic_collection.get("Members", []):
                member_path: str = member.get("@odata.id", "")
                if not member_path:
                    continue
                try:
                    nic = _redfish_get(member_path)
                    interfaces.append(
                        {
                            "name": nic.get("Id", ""),
                            "mac": nic.get("MACAddress", ""),
                            "speed": nic.get("SpeedMbps") or 0,
                        }
                    )
                except Exception as exc:  # pylint: disable=broad-except
                    logger.warning("Could not fetch NIC %s: %s", member_path, exc)
        except Exception as exc:  # pylint: disable=broad-except
            logger.warning("Could not fetch NIC collection: %s", exc)

    # --- Chassis endpoint -------------------------------------------------
    chassis = _redfish_get("/redfish/v1/Chassis/System.Embedded.1")
    model: str = chassis.get("Model") or system.get("Model", "unknown")
    # Dell iDRAC reports the service tag in SKU; fall back to SerialNumber.
    serial: str = (
        chassis.get("SKU")
        or system.get("SKU")
        or chassis.get("SerialNumber")
        or system.get("SerialNumber")
        or "unknown"
    )

    return {
        "hostname": hostname,
        "bmc_address": bmc_address,
        "model": model,
        "serial": serial,
        "system_uuid": system_uuid,
        "cpu_cores": cpu_cores,
        "cpu_model": cpu_model,
        "memory_gib": memory_gib,
        "interfaces": interfaces,
    }


def create_hardware_inventory_cr(
    hardware_info: dict,
    namespace: str = "tink-system",  # noqa: ARG001 — kept for backward-compat; HardwareInventory is cluster-scoped
) -> str:
    """Create or update a HardwareInventory custom resource in Kubernetes.

    Generates a ``HardwareInventory`` CR YAML from *hardware_info* and
    applies it via ``kubectl apply -f -`` (piping YAML to stdin).

    The CR follows the ``provisioning.anpa.aws.io/v1alpha1`` schema as
    defined in ``helm-charts/anpa/crds``. Note that this CRD is
    cluster-scoped, so the ``namespace`` parameter is ignored and kept
    only for backward compatibility with older callers.

    Args:
        hardware_info: Dict as returned by :func:`get_hardware_info`.
        namespace:     Ignored (cluster-scoped CRD). Kept for compat.

    Returns:
        Raw stdout from ``kubectl apply``.

    Raises:
        RuntimeError: If ``kubectl apply`` returns a non-zero exit code.
    """
    hostname: str = hardware_info.get("hostname", hardware_info.get("bmc_address", "unknown"))
    # Kubernetes names must be lowercase DNS labels
    cr_name = hostname.lower().replace("_", "-").replace(".", "-")

    # Build interface YAML lines correctly indented under `spec.interfaces`.
    interfaces = hardware_info.get("interfaces", [])
    if interfaces:
        iface_lines = []
        for iface in interfaces:
            iface_lines.append(f"    - name: {iface.get('name', '')}")
            iface_lines.append(f"      mac: {iface.get('mac', '')}")
            iface_lines.append(f"      speed: \"{iface.get('speed', 0)}\"")
        interfaces_yaml = "  interfaces:\n" + "\n".join(iface_lines)
    else:
        interfaces_yaml = "  interfaces: []"

    yaml_doc = (
        "apiVersion: provisioning.anpa.aws.io/v1alpha1\n"
        "kind: HardwareInventory\n"
        "metadata:\n"
        f"  name: {cr_name}\n"
        "  labels:\n"
        '    provisioning.anpa.aws.io/managed: "true"\n'
        "spec:\n"
        f"  hostname: {hostname}\n"
        f"  bmcAddress: {hardware_info.get('bmc_address', '')}\n"
        f"  systemUUID: {hardware_info.get('system_uuid', '')}\n"
        f"  serialNumber: {hardware_info.get('serial', 'unknown')}\n"
        "  cpu:\n"
        f"    cores: {hardware_info.get('cpu_cores', 0)}\n"
        f"    model: {hardware_info.get('cpu_model', 'unknown')}\n"
        "  memory:\n"
        f"    totalGiB: {hardware_info.get('memory_gib', 0)}\n"
        f"{interfaces_yaml}\n"
    )

    logger.info("Applying HardwareInventory CR for %s", cr_name)
    tmp_fd, tmp_path = tempfile.mkstemp(suffix=".yaml", prefix="anpa-hwinv-")
    try:
        with os.fdopen(tmp_fd, "w") as fh:
            fh.write(yaml_doc)
        result = run_cmd(f"kubectl apply -f {tmp_path}", timeout=30)
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass

    if result.returncode != 0:
        raise RuntimeError(
            f"kubectl apply failed (rc={result.returncode}): {result.stderr}"
        )

    output: str = result.stdout or ""
    logger.info("kubectl apply output: %s", output.strip())
    return output


def reconcile_inventory(
    known_servers: list[dict],
    discovered_servers: list[dict],
) -> dict:
    """Compare known vs. discovered servers and classify changes.

    Servers are matched by their ``serial`` / ``serial_number`` field.

    Args:
        known_servers:      List of server dicts from
                            ``kubectl get hardwareinventories`` (each must
                            contain at least a ``serial`` key).
        discovered_servers: List of server dicts from :func:`scan_redfish_endpoints`
                            (each must contain at least a ``serial`` key).

    Returns:
        Dict with three lists::

            {
                "new":     [...],   # in discovered but not in known
                "removed": [...],   # in known but not in discovered
                "updated": [...],   # serial present in both but other fields differ
            }
    """

    def _serial(server: dict) -> str:
        return (
            server.get("serial")
            or server.get("serial_number")
            or server.get("serialNumber")
            or ""
        ).strip()

    known_by_serial: dict[str, dict] = {_serial(s): s for s in known_servers if _serial(s)}
    discovered_by_serial: dict[str, dict] = {
        _serial(s): s for s in discovered_servers if _serial(s)
    }

    new_servers: list[dict] = [
        s for serial, s in discovered_by_serial.items() if serial not in known_by_serial
    ]
    removed_servers: list[dict] = [
        s for serial, s in known_by_serial.items() if serial not in discovered_by_serial
    ]

    updated_servers: list[dict] = []
    for serial, discovered in discovered_by_serial.items():
        if serial not in known_by_serial:
            continue
        known = known_by_serial[serial]
        # Compare a subset of fields that are meaningful for drift detection
        _cmp_keys = ("model", "cpu_count", "cpu_cores", "memory_gb", "memory_gib", "ip")
        for key in _cmp_keys:
            if discovered.get(key) != known.get(key) and (
                discovered.get(key) is not None or known.get(key) is not None
            ):
                updated_servers.append(
                    {
                        "serial": serial,
                        "known": known,
                        "discovered": discovered,
                    }
                )
                break

    logger.info(
        "Inventory reconciliation: %d new, %d removed, %d updated",
        len(new_servers),
        len(removed_servers),
        len(updated_servers),
    )
    return {
        "new": new_servers,
        "removed": removed_servers,
        "updated": updated_servers,
    }
