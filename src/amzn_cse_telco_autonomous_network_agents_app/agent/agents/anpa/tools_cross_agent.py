# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Cross-agent query tools for ANPA.

These tools allow ANPA's Strands agent to query ANRA and ANDA during
provisioning failure diagnosis (Agents-as-Tools pattern).
"""

import logging

from strands import tool

from amzn_cse_telco_autonomous_network_agents_app.agent.core.executor import run_cmd

log = logging.getLogger(__name__)

_ANRA_BASE = "http://anra.anra-system.svc:8080"
_ANDA_BASE = "http://anda.anda-system.svc:8080"


@tool
def ask_anra_node_health(node_name: str) -> str:
    """Query ANRA for runtime health metrics of a node.

    Use this to cross-validate BMC-reported health with actual OS-level metrics.
    Returns node conditions, resource usage, and recent alarms.

    Args:
        node_name: Kubernetes node name (hostname).
    """
    result = run_cmd(
        f"curl -sf --max-time 10 {_ANRA_BASE}/api/nodes/{node_name}",
        timeout=15,
    )
    if not result.success:
        return f"ANRA unreachable or no data for node '{node_name}': {result.stderr}"
    return result.stdout


@tool
def ask_anra_active_alarms(node_name: str = "") -> str:
    """Query ANRA for currently active alarms, optionally filtered by node.

    Use this during provisioning to check if a newly provisioned node is
    already generating alarms.

    Args:
        node_name: Filter alarms by node (optional, empty = all).
    """
    url = f"{_ANRA_BASE}/api/alarms"
    if node_name:
        url += f"?node={node_name}"
    result = run_cmd(f"curl -sf --max-time 10 {url}", timeout=15)
    if not result.success:
        return f"ANRA unreachable or no alarm data: {result.stderr}"
    return result.stdout


@tool
def ask_anda_workloads_on_node(node_name: str) -> str:
    """Query ANDA for workloads deployed on a specific node.

    Use this to understand what NFs will be affected if a node is
    reprovisioned or taken offline.

    Args:
        node_name: Kubernetes node name.
    """
    result = run_cmd(
        f"curl -sf --max-time 10 {_ANDA_BASE}/api/deployments?node={node_name}",
        timeout=15,
    )
    if not result.success:
        return f"ANDA unreachable or no workload data for node '{node_name}': {result.stderr}"
    return result.stdout


ANPA_CROSS_AGENT_TOOLS = [
    ask_anra_node_health,
    ask_anra_active_alarms,
    ask_anda_workloads_on_node,
]
