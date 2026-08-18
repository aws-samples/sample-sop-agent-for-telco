# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
"""Emit ServiceTopology CR after successful NF deployment."""

import json
import logging
from datetime import datetime, timezone

from amzn_cse_telco_autonomous_network_agents_app.agent.core.executor import run_cmd

logger = logging.getLogger(__name__)

# NF interface catalog — declares 3GPP interfaces (as CRD objects) and type per NF
NF_INTERFACES = {
    "nrf": {"type": "NRF", "interfaces": [{"name": "Nnrf", "protocol": "SBI"}], "dependsOn": []},
    "amf": {"type": "AMF", "interfaces": [{"name": "N1", "protocol": "HTTP2"}, {"name": "N2", "protocol": "SCTP"}, {"name": "Namf", "protocol": "SBI"}], "dependsOn": ["nrf"]},
    "smf": {"type": "SMF", "interfaces": [{"name": "N4", "protocol": "PFCP"}, {"name": "Nsmf", "protocol": "SBI"}], "dependsOn": ["nrf", "amf"]},
    "upf": {"type": "UPF", "interfaces": [{"name": "N3", "protocol": "GTP-U"}, {"name": "N4", "protocol": "PFCP"}, {"name": "N6", "protocol": "IP"}], "dependsOn": ["smf"]},
    "gnb": {"type": "gNB", "interfaces": [{"name": "N2", "protocol": "SCTP"}, {"name": "N3", "protocol": "GTP-U"}], "dependsOn": ["amf", "upf"]},
    "ausf": {"type": "AUSF", "interfaces": [{"name": "Nausf", "protocol": "SBI"}], "dependsOn": ["nrf"]},
    "udm": {"type": "UDM", "interfaces": [{"name": "Nudm", "protocol": "SBI"}], "dependsOn": ["nrf"]},
    "udr": {"type": "UDR", "interfaces": [{"name": "Nudr", "protocol": "SBI"}], "dependsOn": ["nrf"]},
    "pcf": {"type": "PCF", "interfaces": [{"name": "Npcf", "protocol": "SBI"}], "dependsOn": ["nrf"]},
    "nssf": {"type": "NSSF", "interfaces": [{"name": "Nnssf", "protocol": "SBI"}], "dependsOn": ["nrf"]},
}


def update_service_topology(
    site_name: str, deployed_nfs: list[dict], namespace: str = "anra-system"
) -> bool:
    """Create or patch ServiceTopology CR with deployed NFs.

    Args:
        site_name: e.g. "site-002"
        deployed_nfs: list of dicts with keys: name, namespace, chart, version
        namespace: target namespace for the CR

    Returns:
        True if successful, False otherwise.
    """
    # Check config gate
    try:
        from amzn_cse_telco_autonomous_network_agents_app.agent.core.config_store import (
            get_config,
        )

        cfg = get_config()
        if cfg and not cfg.topology_emit_service_topology:
            logger.debug("topology.emit_service_topology is False, skipping")
            return True
    except ImportError:
        pass

    cr_name = f"{site_name}-services"

    # Build NF entries
    nf_entries = []
    for nf in deployed_nfs:
        catalog = NF_INTERFACES.get(
            nf["name"], {"type": nf["name"].upper(), "interfaces": [], "dependsOn": []}  # noqa: E501
        )
        nf_entries.append(
            {
                "name": nf["name"],
                "type": catalog["type"],
                "namespace": nf.get("namespace", "default"),
                "chart": nf.get("chart", ""),
                "version": nf.get("version", ""),
                "interfaces": catalog["interfaces"],
                "dependsOn": catalog["dependsOn"],
                "status": "healthy",
            }
        )

    # Compute links
    links = _compute_links(nf_entries)

    # Build CR (cluster-scoped — no namespace in metadata)
    cr = {
        "apiVersion": "topology.anra.aws.io/v1alpha1",
        "kind": "ServiceTopology",
        "metadata": {"name": cr_name},
        "spec": {
            "siteName": site_name,
            "lastUpdated": datetime.now(timezone.utc).isoformat(),
            "networkFunctions": nf_entries,
            "links": links,
        },
    }

    # Apply via kubectl (pipe JSON through shell; no --namespace for cluster-scoped)
    cr_json = json.dumps(cr)
    escaped_json = cr_json.replace("'", "'\\''")
    cmd = f"echo '{escaped_json}' | kubectl apply -f -"
    result = run_cmd(cmd)
    if result.returncode != 0:
        logger.error("Failed to apply ServiceTopology CR: %s", result.stderr)
        return False
    logger.info("ServiceTopology CR %s updated with %d NFs", cr_name, len(nf_entries))
    return True


def _compute_links(nf_entries: list[dict]) -> list[dict]:
    """Derive links from shared interface names + dependsOn relationships."""
    links = []
    nf_map = {nf["name"]: nf for nf in nf_entries}

    for nf in nf_entries:
        for dep_name in nf.get("dependsOn", []):
            if dep_name not in nf_map:
                continue
            dep = nf_map[dep_name]
            # Find shared interface names
            nf_iface_names = {i["name"] for i in nf["interfaces"]}
            dep_iface_names = {i["name"] for i in dep["interfaces"]}
            shared = nf_iface_names & dep_iface_names
            for iface in sorted(shared):
                links.append(
                    {"from": nf["name"], "to": dep_name, "interface": iface}
                )

    return links
