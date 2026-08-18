# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
"""Server-group entry generator — operator/manual Git path (P3.2, demoted P5.4).

.. note::

    **This module is NOT used by the autonomous reconciler.**

    Per ADR-0001 (revised 2026-05-31), ANPA's autonomous flow emits the
    EKS-H ``BareMetalProvision`` CR directly via
    :func:`agent.agents.anpa.reconciler._emit_baremetal_provision_cr`.
    EKS-H's ``bare-metal-kro`` RGD then materializes the Tinkerbell
    Workflow.

    This generator stays in the repo for **operator-driven manual
    provisioning** through EKS-H's GitOps path: a human authors a
    ``server-groups/<cluster>/<group>.yaml`` entry, opens a PR, ArgoCD
    syncs, and EKS-H's ``bare-metal`` Application materializes the
    BareMetalProvision after merge. This is the same path Cheng-Ian-Liu's
    team uses; we don't break it.

    Operators / CLIs / scripts may still import :func:`generate_yaml`.
    The reconciler does not.

Pure function: given a discovered HardwareInventory ``.spec`` plus a
provisioning intent dict, produce a YAML document compatible with the
EKS-H ``server-groups/<cluster>/<group>.yaml`` schema (see
``day0/server-groups/example.yaml``).

The generator never does I/O. It does NOT:
  - load HardwareInventory CRs from the cluster,
  - select/derive secret values (BMC password is referenced by name, not value),
  - decide *whether* a server should be provisioned (that's `policy.py`),
  - produce the 25-field BareMetalProvision (Helm/kro do that downstream).

Inputs and outputs are dicts/strings so this module is trivial to unit-test.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import yaml

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Intent schema (what the operator/ANPA decides — not what's discovered)
# ---------------------------------------------------------------------------


@dataclass
class ProvisioningIntent:
    """Caller-supplied facts that ANPA's discovery cannot determine on its own.

    Discovery learns hostname, MAC, BMC, hardware specs from Redfish.
    These fields encode the *policy* of what to do with that server.
    """
    cluster_name: str           # workload cluster the server should join
    cluster_region: str         # AWS region of that cluster
    group_name: str             # server-group bucket (e.g. "site-002-rack-1")
    machine_profile: str        # references machineProfiles.<name> in bare-metal values
    os_profile: str             # references osProfiles.<name>
    network_profile: str        # references networkProfiles.<name>
    tuning_profile: str = "none"  # references tuningProfiles.<name> or "none"
    bmc_user: str = "root"
    bmc_pass_secret_ref: str = "${BMC_PASS}"  # by reference, never the literal
    role: str = "worker"
    provision: bool = False     # default false — operator/policy enables explicitly
    provision_hash: str = "v1"
    ip: str | None = None       # operator-supplied; ANPA doesn't have IPAM today
    overrides: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Pure generator
# ---------------------------------------------------------------------------


def _resolve_first_mac(hwi: dict) -> str:
    """Return the first interface MAC, or '' when discovery captured none."""
    interfaces = hwi.get("interfaces") or []
    for iface in interfaces:
        mac = (iface or {}).get("mac")
        if mac:
            return mac
    return ""


def generate_server_entry(
    hardware_inventory: dict,
    intent: ProvisioningIntent,
) -> dict:
    """Build a single server entry dict (the items in ``servers:``).

    Args:
        hardware_inventory: HardwareInventory ``.spec`` dict (what discovery
                            wrote to the cluster), with at minimum
                            ``hostname``, ``bmcAddress``, and optionally
                            ``interfaces[].mac``.
        intent:             :class:`ProvisioningIntent` — operator policy.

    Returns:
        dict matching the EKS-H per-server schema.
    """
    hostname = hardware_inventory.get("hostname")
    bmc = hardware_inventory.get("bmcAddress")
    if not hostname or not bmc:
        raise ValueError("hardware_inventory must include hostname and bmcAddress")

    entry: dict[str, Any] = {
        "name": hostname,
        "machineProfile": intent.machine_profile,
        "osProfile": intent.os_profile,
        "networkProfile": intent.network_profile,
        "tuningProfile": intent.tuning_profile,
        "ip": intent.ip or "",
        "mac": _resolve_first_mac(hardware_inventory),
        "bmcAddress": bmc,
        "bmcUser": intent.bmc_user,
        "bmcPass": intent.bmc_pass_secret_ref,
        "provision": intent.provision,
        "provisionHash": intent.provision_hash,
    }
    # Apply caller-supplied overrides last (e.g. role, custom annotations).
    entry.update(intent.overrides or {})
    return entry


def generate_group_document(
    hardware_inventories: list[dict],
    intent: ProvisioningIntent,
) -> dict:
    """Build the full ``server-groups/<cluster>/<group>.yaml`` document.

    Args:
        hardware_inventories: list of HardwareInventory ``.spec`` dicts.
        intent:               :class:`ProvisioningIntent`.

    Returns:
        dict with ``cluster``, ``groupName``, ``servers``.
    """
    return {
        "cluster": {
            "name": intent.cluster_name,
            "region": intent.cluster_region,
        },
        "groupName": intent.group_name,
        "servers": [generate_server_entry(hwi, intent) for hwi in hardware_inventories],
    }


def to_yaml(document: dict) -> str:
    """Render a document with stable key ordering and clean formatting."""
    return yaml.safe_dump(document, default_flow_style=False, sort_keys=False)


# ---------------------------------------------------------------------------
# Public convenience
# ---------------------------------------------------------------------------


def generate_yaml(
    hardware_inventories: list[dict],
    intent: ProvisioningIntent,
) -> str:
    """One-shot: HardwareInventories + intent → server-group YAML string."""
    return to_yaml(generate_group_document(hardware_inventories, intent))
