# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
"""Hardware-aware tuning generator — Phase 3.3.

Derives EKS-H ``tuningProfiles.<name>`` content (kernelCmdline + sysctl)
from a discovered CPU topology and an NF profile. Pure functions only.

The output shape mirrors the existing EKS-H ``high-performance`` profile
in ``day0/.../tinkerbell/bare-metal/values.yaml``::

    tuningProfile-name:
      kernelCmdline: "intel_iommu=on iommu=pt hugepagesz=1G hugepages=8 ..."
      sysctl: { ... }
      disabledServices: [irqbalance]

This module makes one inevitable simplifying choice: it allocates a fixed
set of "house" cores per socket (default 2) for OS/kubelet, and isolates
the rest. That heuristic matches what the EKS-H tuningProfiles reference
example does and is consistent with telco DPDK practice.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

# Reserved per-socket cores for OS / k8s housekeeping (not isolated).
_HOUSEKEEPING_CORES_PER_SOCKET = 2


@dataclass
class TuningRequest:
    """What the NF wants. Sourced from configs/nf-profiles/<nf>.yaml."""
    nf: str
    hugepages_1gi: int = 8                # hugepagesz=1G hugepages=N
    sysctl_overrides: dict[str, str] | None = None
    disabled_services: list[str] | None = None


def _isolated_cpu_mask(sockets: int, cores_per_socket: int) -> str:
    """Return the isolcpus range string e.g. '2-31,34-63' for a 2-socket box.

    Reserves the first ``_HOUSEKEEPING_CORES_PER_SOCKET`` cores on each
    socket for the OS, isolates the remainder. CPUs are numbered with
    socket-major ordering, which is the de-facto Linux convention for the
    boxes this platform targets (Dell PowerEdge / HPE / Supermicro).
    """
    if sockets <= 0 or cores_per_socket <= 0:
        return ""
    ranges = []
    for s in range(sockets):
        socket_start = s * cores_per_socket
        iso_start = socket_start + _HOUSEKEEPING_CORES_PER_SOCKET
        iso_end = socket_start + cores_per_socket - 1
        if iso_end >= iso_start:
            ranges.append(f"{iso_start}-{iso_end}")
    return ",".join(ranges)


def generate_tuning_profile(
    topology: dict,
    request: TuningRequest,
) -> dict[str, Any]:
    """Return a tuningProfile dict for a specific server topology + NF.

    Args:
        topology: output of ``bios_inspector.get_processor_topology``.
                  Required keys: ``sockets``, ``total_cores``.
        request:  :class:`TuningRequest`.

    Returns:
        ``{"kernelCmdline": str, "sysctl": dict, "disabledServices": list}``.
    """
    sockets = int(topology.get("sockets") or 0)
    total_cores = int(topology.get("total_cores") or 0)
    cores_per_socket = total_cores // sockets if sockets else 0

    iso_mask = _isolated_cpu_mask(sockets, cores_per_socket)

    kernel_args: list[str] = [
        "intel_iommu=on",
        "iommu=pt",
        "hugepagesz=1G",
        f"hugepages={request.hugepages_1gi}",
    ]
    if iso_mask:
        kernel_args.append(f"isolcpus={iso_mask}")
        kernel_args.append(f"nohz_full={iso_mask}")
        kernel_args.append(f"rcu_nocbs={iso_mask}")

    sysctl: dict[str, str] = {
        "vm.nr_hugepages": str(request.hugepages_1gi),
        "net.core.rmem_max": "16777216",
        "net.core.wmem_max": "16777216",
        "net.core.busy_poll": "50",
        "net.core.busy_read": "50",
    }
    if request.sysctl_overrides:
        sysctl.update(request.sysctl_overrides)

    disabled = list(request.disabled_services or ["irqbalance"])

    return {
        "kernelCmdline": " ".join(kernel_args),
        "sysctl": sysctl,
        "disabledServices": disabled,
    }


def generate_tuning_fields(
    topology: dict,
    request: TuningRequest,
) -> dict[str, str]:
    """Phase 5.3 — RGD-direct tuning fields for the BareMetalProvision CR.

    Per ADR-0001 (revised), ANPA emits the EKS-H ``BareMetalProvision`` CR
    directly. That CR carries three string-typed tuning fields
    (see ``day0/.../bare-metal-kro/provision-rgd.yaml`` lines 47–49):

      * ``tuningKernelCmdline``   — space-separated kernel args
      * ``tuningSysctl``          — semicolon-separated ``key=value`` pairs (sorted)
      * ``tuningDisabledServices``— comma-separated systemd unit names

    These serialization conventions match how EKS-H's bare-metal Helm
    template (``bare-metal-server.yaml``) renders them from the
    ``tuningProfiles`` values catalog, so ANPA-emitted CRs are
    indistinguishable from operator-driven ones to the downstream
    Tinkerbell ``Workflow`` (``template.yaml`` does ``tr ';' '\\n'`` on
    sysctl and writes ``/etc/sysctl.d/99-tuning.conf``).

    The original :func:`generate_tuning_profile` remains for the operator
    manual values-catalog path; this function is the autonomous-flow
    counterpart.

    Args:
        topology: output of ``bios_inspector.get_processor_topology``
                  (requires ``sockets`` and ``total_cores``).
        request:  :class:`TuningRequest`.

    Returns:
        ``{"tuningKernelCmdline": str, "tuningSysctl": str,
           "tuningDisabledServices": str}``

    Notes:
        Sysctl keys are sorted alphabetically to match the EKS-H Helm
        template's ``sortAlpha`` rendering — keeps generated CRs stable
        across re-emits and easy to diff.
    """
    profile = generate_tuning_profile(topology, request)

    sysctl_pairs = [f"{k}={v}" for k, v in sorted(profile["sysctl"].items())]

    return {
        "tuningKernelCmdline": profile["kernelCmdline"],
        "tuningSysctl": ";".join(sysctl_pairs),
        "tuningDisabledServices": ",".join(profile["disabledServices"]),
    }


def tuning_profile_name(nf: str, hostname: str) -> str:
    """Derive a deterministic profile name for the bare-metal values catalog."""
    safe_host = hostname.lower().replace("_", "-").replace(".", "-")
    return f"{nf.lower()}-{safe_host}"
