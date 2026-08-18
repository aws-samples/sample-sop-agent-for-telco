# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Cross-agent query tools for ANDA.

These tools allow ANDA's Strands agent to query ANRA and ANPA during
deployment orchestration (Agents-as-Tools pattern).
"""

import logging

from strands import tool

from amzn_cse_telco_autonomous_network_agents_app.agent.core.executor import run_cmd

log = logging.getLogger(__name__)

_ANRA_BASE = "http://anra.anra-system.svc:8080"
_ANPA_BASE = "http://anpa.anpa-system.svc:8080"


@tool
def ask_anra_cluster_health(namespace: str = "") -> str:
    """Query ANRA for current cluster health before deploying.

    Use this in preflight to ensure no active incidents that would make
    a deployment risky.

    Args:
        namespace: Check health for a specific namespace (optional).
    """
    url = f"{_ANRA_BASE}/api/alarms"
    if namespace:
        url += f"?namespace={namespace}"
    result = run_cmd(f"curl -sf --max-time 10 {url}", timeout=15)
    if not result.success:
        return f"ANRA unreachable or no health data: {result.stderr}"
    return result.stdout


@tool
def ask_anpa_node_readiness(node_name: str) -> str:
    """Query ANPA for whether a node is fully provisioned and ready.

    Use this before scheduling workloads on a node to confirm it passed
    all provisioning checks.

    Args:
        node_name: Kubernetes node name (hostname).
    """
    result = run_cmd(
        f"curl -sf --max-time 10 {_ANPA_BASE}/api/provisioning/requests?server={node_name}",
        timeout=15,
    )
    if not result.success:
        return f"ANPA unreachable or no data for node '{node_name}': {result.stderr}"
    return result.stdout


ANDA_CROSS_AGENT_TOOLS = [
    ask_anra_cluster_health,
    ask_anpa_node_readiness,
]
