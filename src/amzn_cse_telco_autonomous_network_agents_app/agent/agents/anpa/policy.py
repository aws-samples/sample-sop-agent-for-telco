# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""
Provisioning policy engine for ANPA (Autonomous Node Provisioning Agent).

All functions in this module are **pure** (no side effects, no I/O, no
``run_cmd`` calls) so they can be unit-tested in isolation without any
cluster access.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Default OS image mappings
# ---------------------------------------------------------------------------
_DEFAULT_IMAGE = "ubuntu-2204-eks-hybrid"
_ROLE_IMAGE_MAP = {
    "worker": _DEFAULT_IMAGE,
    "ran-worker": "ubuntu-2204-eks-hybrid-rt",
    "control-plane": _DEFAULT_IMAGE,
}


# ---------------------------------------------------------------------------
# Provision / deprovision decisions
# ---------------------------------------------------------------------------


def should_provision(
    server: dict,
    cluster_status: dict,
    config: dict,
) -> tuple[bool, str]:
    """Decide whether a server should be provisioned as a cluster node.

    Checks (in order):

    1. Server phase is ``"Available"``.
    2. Cluster needs additional capacity (node count < threshold).
    3. Current time is **not** inside a maintenance window.
    4. BMC is reported as healthy.
    5. Number of concurrently-provisioning nodes is below ``max_concurrent``.

    Args:
        server:         Server dict (``phase``, ``bmc_healthy``, optional
                        ``provisioning_state``).
        cluster_status: Cluster dict (``current_nodes``, ``desired_nodes``,
                        ``provisioning_count``).
        config:         Policy config dict with optional keys:

                        * ``maintenance_windows`` – list of window dicts.
                        * ``capacity_threshold``  – minimum desired-to-current
                          ratio that triggers provisioning (default ``1.0``).
                        * ``max_concurrent``      – max parallel provisions
                          (default ``3``).

    Returns:
        ``(True, reason)`` if the server should be provisioned;
        ``(False, reason)`` otherwise.
    """
    # --- Phase check -------------------------------------------------------
    phase: str = server.get("phase", "")
    if phase != "Available":
        return False, f"Server phase is '{phase}', expected 'Available'"

    # --- Capacity check ----------------------------------------------------
    current_nodes: int = cluster_status.get("current_nodes", 0)
    desired_nodes: int = cluster_status.get("desired_nodes", 0)
    capacity_threshold: float = float(config.get("capacity_threshold", 1.0))

    if desired_nodes > 0:
        ratio = current_nodes / desired_nodes
        if ratio >= capacity_threshold:
            return (
                False,
                f"Cluster at capacity ({current_nodes}/{desired_nodes} nodes, "
                f"threshold={capacity_threshold})",
            )
    elif desired_nodes == 0 and current_nodes > 0:
        return False, "Cluster has no desired nodes; nothing to provision"

    # --- Maintenance window check ------------------------------------------
    maintenance_windows: list = config.get("maintenance_windows", [])
    if is_in_maintenance_window(maintenance_windows):
        return False, "Current time is within a maintenance window"

    # --- BMC health check --------------------------------------------------
    bmc_healthy: bool = bool(server.get("bmc_healthy", True))
    if not bmc_healthy:
        return False, "BMC is not healthy"

    # --- Concurrency check -------------------------------------------------
    max_concurrent: int = int(config.get("max_concurrent", 3))
    provisioning_count: int = cluster_status.get("provisioning_count", 0)
    if provisioning_count >= max_concurrent:
        return (
            False,
            f"Max concurrent provisioning limit reached "
            f"({provisioning_count}/{max_concurrent})",
        )

    return True, "All policy checks passed; server is eligible for provisioning"


def should_deprovision(
    server: dict,
    cluster_status: dict,
    config: dict,
) -> tuple[bool, str]:
    """Decide whether a server should be deprovisioned.

    Checks (in order):

    1. Node has been ``NotReady`` longer than ``not_ready_threshold_seconds``
       (default 300 s).
    2. A hardware fault has been detected (``hardware_fault == True``).
    3. Cluster is over-provisioned (node count exceeds desired by more than
       ``over_provision_buffer``, default 0).

    Args:
        server:         Server dict (``not_ready_seconds``, ``hardware_fault``,
                        ``phase``).
        cluster_status: Cluster dict (``current_nodes``, ``desired_nodes``).
        config:         Policy config dict with optional keys:

                        * ``not_ready_threshold_seconds`` (default ``300``).
                        * ``over_provision_buffer``        (default ``0``).

    Returns:
        ``(True, reason)`` if the server should be deprovisioned;
        ``(False, reason)`` otherwise.
    """
    # --- NotReady duration check -------------------------------------------
    not_ready_seconds: int = int(server.get("not_ready_seconds", 0))
    threshold_seconds: int = int(config.get("not_ready_threshold_seconds", 300))
    if not_ready_seconds > threshold_seconds:
        return (
            True,
            f"Node has been NotReady for {not_ready_seconds}s "
            f"(threshold={threshold_seconds}s)",
        )

    # --- Hardware fault check ----------------------------------------------
    hardware_fault: bool = bool(server.get("hardware_fault", False))
    if hardware_fault:
        return True, "Hardware fault detected on server"

    # --- Over-provisioned check --------------------------------------------
    current_nodes: int = cluster_status.get("current_nodes", 0)
    desired_nodes: int = cluster_status.get("desired_nodes", 0)
    over_provision_buffer: int = int(config.get("over_provision_buffer", 0))
    if current_nodes > desired_nodes + over_provision_buffer:
        return (
            True,
            f"Cluster is over-provisioned ({current_nodes} nodes, "
            f"desired={desired_nodes}, buffer={over_provision_buffer})",
        )

    return False, "No deprovision conditions met"


# ---------------------------------------------------------------------------
# Wave planning
# ---------------------------------------------------------------------------


def get_provision_wave(
    servers: list,
    max_concurrent: int = 3,
) -> "list":
    """Batch servers into waves to avoid thundering-herd problems.

    Args:
        servers:        List of server dicts to provision.
        max_concurrent: Maximum number of servers in a single wave
                        (default ``3``).

    Returns:
        List of lists.  Each inner list is a wave of servers that can be
        provisioned in parallel.  The order of waves preserves the original
        order of *servers*.

    Example::

        >>> get_provision_wave([s1, s2, s3, s4, s5], max_concurrent=2)
        [[s1, s2], [s3, s4], [s5]]
    """
    if max_concurrent < 1:
        raise ValueError(f"max_concurrent must be >= 1, got {max_concurrent}")

    waves = []
    for i in range(0, len(servers), max_concurrent):
        waves.append(servers[i : i + max_concurrent])

    logger.debug(
        "Created %d wave(s) for %d server(s) (max_concurrent=%d)",
        len(waves),
        len(servers),
        max_concurrent,
    )
    return waves


# ---------------------------------------------------------------------------
# OS image selection
# ---------------------------------------------------------------------------


def get_os_image(server: dict, image_profiles: dict) -> str:
    """Map a server's role to an OS image profile name.

    Lookup order:

    1. ``image_profiles[role]``  – caller-supplied overrides.
    2. Built-in ``_ROLE_IMAGE_MAP[role]``.
    3. ``_DEFAULT_IMAGE``        – fallback.

    Args:
        server:         Server dict containing an optional ``role`` key.
        image_profiles: Caller-supplied mapping of role → image name.
                        Takes precedence over built-in defaults.

    Returns:
        OS image profile name string.
    """
    role: str = server.get("role", "worker")

    image = (
        image_profiles.get(role)
        or _ROLE_IMAGE_MAP.get(role)
        or _DEFAULT_IMAGE
    )

    logger.debug("Resolved OS image for role '%s': %s", role, image)
    return image


# ---------------------------------------------------------------------------
# Maintenance window
# ---------------------------------------------------------------------------


def is_in_maintenance_window(windows: list) -> bool:
    """Check whether the current UTC time falls inside any maintenance window.

    Each window dict must contain:

    * ``day_of_week``    – ISO weekday (Monday=1 … Sunday=7) or 0-indexed
                          (Sunday=0 … Saturday=6).  Both conventions are
                          handled: if ``day_of_week == 0`` it is treated as
                          Sunday (isoweekday 7).
    * ``start_hour``     – UTC hour (0–23) when the window opens.
    * ``duration_hours`` – Length of the window in hours (> 0).

    The function is intentionally lenient: unknown keys are ignored and any
    window that cannot be parsed is skipped with a warning.

    Args:
        windows: List of maintenance-window dicts.

    Returns:
        ``True`` if the current time is inside at least one window;
        ``False`` otherwise.
    """
    if not windows:
        return False

    now: datetime = datetime.now(tz=timezone.utc)
    current_weekday: int = now.isoweekday()  # Monday=1, Sunday=7
    current_hour: int = now.hour

    for window in windows:
        try:
            raw_day: int = int(window["day_of_week"])
            start_hour: int = int(window["start_hour"])
            duration_hours: int = int(window["duration_hours"])
        except (KeyError, TypeError, ValueError) as exc:
            logger.warning("Skipping malformed maintenance window %s: %s", window, exc)
            continue

        if duration_hours <= 0:
            logger.warning("Skipping window with non-positive duration: %s", window)
            continue

        # Normalise 0-indexed Sunday (0) → isoweekday 7
        iso_day: int = 7 if raw_day == 0 else raw_day

        if iso_day != current_weekday:
            continue

        # Check if current hour falls within [start_hour, start_hour + duration)
        # Handle windows that wrap across midnight
        end_hour: int = start_hour + duration_hours
        if end_hour <= 24:
            # Window stays within a single calendar day
            if start_hour <= current_hour < end_hour:
                logger.info(
                    "Current time %s is within maintenance window %s", now, window
                )
                return True
        else:
            # Window wraps past midnight
            if current_hour >= start_hour or current_hour < (end_hour % 24):
                logger.info(
                    "Current time %s is within maintenance window %s", now, window
                )
                return True

    return False
