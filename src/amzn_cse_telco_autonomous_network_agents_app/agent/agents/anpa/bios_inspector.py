# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
"""BIOS + firmware inspection helpers (read-only Redfish).

These are *primitives* — they fetch raw structured data from a Dell iDRAC.
Vendor-specific attribute name mapping is intentionally minimal here; the
preflight reasoner is responsible for evaluating these against a target
NF profile (see :mod:`agent.agents.anpa.preflight_reasoner`).
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any


logger = logging.getLogger(__name__)


def _curl(url: str, username: str, password: str, timeout: int = 15) -> tuple[bool, dict]:
    """Issue a Redfish GET via curl and parse JSON. Returns (ok, body).

    Credentials are passed via curl's stdin config (see util.bmc.curl_bmc), never
    interpolated into a command string.
    """
    from amzn_cse_telco_autonomous_network_agents_app.agent.util.bmc import curl_bmc

    result = curl_bmc(url, username, password, timeout=timeout)
    if result.returncode != 0:
        logger.warning("Redfish GET %s failed (rc=%d)", url, result.returncode)
        return False, {}
    try:
        return True, json.loads(result.stdout or "{}")
    except json.JSONDecodeError as exc:
        logger.warning("Redfish GET %s returned non-JSON: %s", url, exc)
        return False, {}


def _resolve_creds(username: str | None, password: str | None) -> tuple[str, str]:
    return (
        username if username is not None else os.environ.get("BMC_USERNAME", "root"),
        password if password is not None else os.environ.get("BMC_PASSWORD", ""),
    )


def get_bios_attributes(
    bmc_address: str,
    username: str | None = None,
    password: str | None = None,
) -> dict[str, Any]:
    """Return a flattened map of BIOS attributes from a Dell iDRAC.

    Reads ``/redfish/v1/Systems/System.Embedded.1/Bios`` and returns
    ``Attributes`` verbatim. Common keys for NF readiness include:

    * ``BootMode`` -- ``Uefi`` or ``Bios``
    * ``SriovGlobalEnable`` -- ``Enabled``/``Disabled``
    * ``LogicalProc`` -- HT (``Enabled`` = on)
    * ``ProcCStates`` -- ``Enabled``/``Disabled``
    * ``EnergyPerformanceBias`` -- ``MaxPower`` for telco NFs
    * ``MemFrequency`` -- ``MaxPerf``
    * ``SubNumaCluster`` -- ``Enabled``/``Disabled``
    * ``SecureBoot`` -- ``Enabled``/``Disabled``

    Attribute names match the iDRAC Redfish vocabulary; consumers should
    treat unknown vendors as best-effort and fall through gracefully.
    """
    user, pwd = _resolve_creds(username, password)
    ok, body = _curl(
        f"https://{bmc_address}/redfish/v1/Systems/System.Embedded.1/Bios",
        user, pwd,
    )
    if not ok:
        return {}
    return body.get("Attributes", {}) or {}


def get_firmware_inventory(
    bmc_address: str,
    username: str | None = None,
    password: str | None = None,
) -> list[dict[str, str]]:
    """Return [{name, version, id}, ...] for every firmware component.

    Walks ``/redfish/v1/UpdateService/FirmwareInventory`` and dereferences
    each member. Best-effort: components that fail to fetch are skipped.
    """
    user, pwd = _resolve_creds(username, password)
    ok, listing = _curl(
        f"https://{bmc_address}/redfish/v1/UpdateService/FirmwareInventory",
        user, pwd,
    )
    if not ok:
        return []
    out: list[dict[str, str]] = []
    for member in listing.get("Members", []):
        path = member.get("@odata.id")
        if not path:
            continue
        ok, item = _curl(f"https://{bmc_address}{path}", user, pwd)
        if not ok:
            continue
        out.append({
            "id": item.get("Id", ""),
            "name": item.get("Name") or item.get("SoftwareId", ""),
            "version": item.get("Version", ""),
            "updateable": bool(item.get("Updateable", False)),
        })
    return out


def get_processor_topology(
    bmc_address: str,
    username: str | None = None,
    password: str | None = None,
) -> dict[str, Any]:
    """Return CPU topology summary: socket count, total cores/threads, models.

    Walks ``/redfish/v1/Systems/System.Embedded.1/Processors`` and aggregates.
    Output keys:
      sockets, total_cores, total_threads, models (list of unique strings).
    """
    user, pwd = _resolve_creds(username, password)
    ok, listing = _curl(
        f"https://{bmc_address}/redfish/v1/Systems/System.Embedded.1/Processors",
        user, pwd,
    )
    if not ok:
        return {"sockets": 0, "total_cores": 0, "total_threads": 0, "models": []}

    sockets = 0
    total_cores = 0
    total_threads = 0
    models: set[str] = set()
    for member in listing.get("Members", []):
        path = member.get("@odata.id")
        if not path:
            continue
        ok, item = _curl(f"https://{bmc_address}{path}", user, pwd)
        if not ok:
            continue
        # Skip non-CPU entries (some Dells expose accelerators here)
        if (item.get("ProcessorType") or "CPU") != "CPU":
            continue
        sockets += 1
        total_cores += int(item.get("TotalCores") or 0)
        total_threads += int(item.get("TotalThreads") or 0)
        if item.get("Model"):
            models.add(str(item["Model"]).strip())

    return {
        "sockets": sockets,
        "total_cores": total_cores,
        "total_threads": total_threads,
        "models": sorted(models),
    }
