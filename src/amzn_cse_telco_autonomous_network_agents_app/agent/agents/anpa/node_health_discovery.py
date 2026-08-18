# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""ANPA node health + discovery: cluster health check + Redfish discovery.

Extracted from reconciler.py for cohesion. These run on the reconciler's
periodic cadence, independent of the per-request state machine.
"""

from __future__ import annotations

import json
import logging

from amzn_cse_telco_autonomous_network_agents_app.agent.config import load_config
from amzn_cse_telco_autonomous_network_agents_app.agent.core.executor import run_cmd

logger = logging.getLogger(__name__)


def _check_node_health() -> None:
    """Inspect all cluster nodes and log warnings for any that are ``NotReady``.

    Specifically flags hybrid nodes (label
    ``eks.amazonaws.com/compute-type=hybrid``) so that they can be correlated
    with pending provisioning requests.
    """
    result = run_cmd("kubectl get nodes -o json", timeout=30)
    if not result.success:
        logger.warning("Failed to get nodes: %s", result.stderr)
        return

    try:
        nodes: list = json.loads(result.stdout or "{}").get("items", [])
    except json.JSONDecodeError as exc:
        logger.warning("Could not parse nodes JSON: %s", exc)
        return

    not_ready: list[str] = []
    for node in nodes:
        node_name: str = node.get("metadata", {}).get("name", "unknown")
        labels: dict = node.get("metadata", {}).get("labels", {})
        compute_type: str = labels.get("eks.amazonaws.com/compute-type", "")

        for cond in node.get("status", {}).get("conditions", []):
            if cond.get("type") == "Ready" and cond.get("status") != "True":
                not_ready.append(node_name)
                logger.warning(
                    "Node %s is NotReady (status=%s%s): %s",
                    node_name,
                    cond.get("status", "Unknown"),
                    ", hybrid=true" if compute_type == "hybrid" else "",
                    cond.get("message", ""),
                )
                break

    if not_ready:
        logger.warning("%d node(s) NotReady: %s", len(not_ready), ", ".join(not_ready))
    else:
        logger.debug("Node health check: all nodes are Ready")


def _run_discovery() -> None:
    """Scan configured BMC subnets for Redfish endpoints and register new servers.

    If no subnets can be inferred from site config, the function returns
    immediately without error.
    """
    from amzn_cse_telco_autonomous_network_agents_app.agent.agents.anpa import discovery  # pylint: disable=import-outside-toplevel

    config = load_config()
    namespace: str = config.tinkerbell_namespace

    # Derive unique /24 subnets from all known BMC IPs
    subnets: list[str] = []
    for node in config.nodes:
        if node.bmc.ip:
            octets = node.bmc.ip.rsplit(".", 1)
            if len(octets) == 2:
                subnets.append(f"{octets[0]}.0/24")
    subnets = list(dict.fromkeys(subnets))  # deduplicate, preserve insertion order

    if not subnets:
        logger.debug("No BMC subnets derivable from config; skipping Redfish discovery")
        return

    total_registered = 0
    for subnet in subnets:
        logger.info("Running Redfish discovery on subnet %s", subnet)
        try:
            discovered = discovery.scan_redfish_endpoints(subnet_cidr=subnet)
            for hw in discovered:
                try:
                    discovery.create_hardware_inventory_cr(hw, namespace=namespace)
                    total_registered += 1
                except Exception as exc:  # pylint: disable=broad-except
                    logger.warning(
                        "Failed to register discovered server %s: %s",
                        hw.get("hostname", hw.get("ip", "?")),
                        exc,
                    )
        except Exception as exc:  # pylint: disable=broad-except
            logger.warning("Redfish scan of %s failed: %s", subnet, exc)

    logger.info("Discovery scan complete: %d server(s) registered", total_registered)
