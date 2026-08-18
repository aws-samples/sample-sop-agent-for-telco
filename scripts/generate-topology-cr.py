#!/usr/bin/env python3
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""
generate-topology-cr.py — Generate a PhysicalTopology CR from live cluster state.

Reads node information from `kubectl get nodes` and HardwareInventory CRs,
then outputs a PhysicalTopology CR YAML that describes the physical layout of
the site. The topology controller watches this CR to compute ImpactMaps.

Usage:
    # Generate and print to stdout
    python scripts/generate-topology-cr.py

    # Generate and apply directly
    python scripts/generate-topology-cr.py | kubectl apply -f -

    # Generate for a specific site name
    python scripts/generate-topology-cr.py --site-name site-002

    # Include HardwareInventory details (BMC, CPU, memory)
    python scripts/generate-topology-cr.py --include-hardware

    # Output to file
    python scripts/generate-topology-cr.py -o manifests/topology/site-002-physical.yaml

Environment:
    KUBECONFIG — Path to kubeconfig (optional, uses default context)
    SITE_NAME  — Override site name (default: derived from cluster name)

Resolves: CSE-3019
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
import sys
from datetime import datetime, timezone
from typing import Any

import yaml

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# kubectl helpers
# ---------------------------------------------------------------------------

def run_kubectl(args: str, timeout: int = 30) -> dict | list | None:
    """Run a kubectl command and return parsed JSON output."""
    cmd = f"kubectl {args}"
    try:
        result = subprocess.run(
            cmd, shell=True, capture_output=True, text=True, timeout=timeout
        )
        if result.returncode != 0:
            logger.warning("kubectl failed: %s", result.stderr.strip())
            return None
        return json.loads(result.stdout) if result.stdout.strip() else None
    except (subprocess.TimeoutExpired, json.JSONDecodeError) as exc:
        logger.warning("kubectl error: %s", exc)
        return None


def get_nodes() -> list[dict]:
    """Get all cluster nodes."""
    data = run_kubectl("get nodes -o json")
    if not data:
        return []
    return data.get("items", [])


def get_hardware_inventories() -> list[dict]:
    """Get all HardwareInventory CRs (if they exist)."""
    data = run_kubectl("get hardwareinventories -A -o json --ignore-not-found")
    if not data:
        return []
    return data.get("items", [])


def get_cluster_name() -> str:
    """Derive cluster name from current context."""
    try:
        result = subprocess.run(
            "kubectl config current-context",
            shell=True, capture_output=True, text=True, timeout=10,
        )
        context = result.stdout.strip()
        # EKS context format: arn:aws:eks:REGION:ACCOUNT:cluster/CLUSTER_NAME
        if "cluster/" in context:
            return context.split("cluster/")[-1]
        return context
    except Exception:
        return "unknown"


# ---------------------------------------------------------------------------
# Node classification
# ---------------------------------------------------------------------------

def classify_node(node: dict) -> dict[str, Any]:
    """Extract structured info from a K8s Node object."""
    metadata = node.get("metadata", {})
    labels = metadata.get("labels", {})
    status = node.get("status", {})
    addresses = status.get("addresses", [])
    node_info = status.get("nodeInfo", {})
    conditions = status.get("conditions", [])

    # Determine node type
    compute_type = labels.get("eks.amazonaws.com/compute-type", "vpc")
    is_hybrid = compute_type == "hybrid"

    # Determine role from labels
    role = "worker"
    if "node-role.kubernetes.io/control-plane" in labels:
        role = "control-plane"
    elif is_hybrid:
        # Hybrid nodes are on-prem bare metal — could be ran/core/edge
        role = "edge"

    # Get addresses
    internal_ip = ""
    hostname = metadata.get("name", "")
    for addr in addresses:
        if addr.get("type") == "InternalIP":
            internal_ip = addr.get("address", "")
        elif addr.get("type") == "Hostname":
            hostname = addr.get("address", hostname)

    # Get ready status
    ready = False
    for cond in conditions:
        if cond.get("type") == "Ready":
            ready = cond.get("status") == "True"
            break

    # Capacity
    capacity = status.get("capacity", {})

    return {
        "name": metadata.get("name", ""),
        "hostname": hostname,
        "internalIP": internal_ip,
        "role": role,
        "computeType": compute_type,
        "isHybrid": is_hybrid,
        "ready": ready,
        "labels": labels,
        "arch": node_info.get("architecture", "amd64"),
        "os": node_info.get("osImage", ""),
        "kernelVersion": node_info.get("kernelVersion", ""),
        "containerRuntime": node_info.get("containerRuntimeVersion", ""),
        "kubeletVersion": node_info.get("kubeletVersion", ""),
        "capacity": {
            "cpu": capacity.get("cpu", "0"),
            "memory": capacity.get("memory", "0"),
            "pods": capacity.get("pods", "0"),
        },
    }


def enrich_with_hardware(
    server: dict, hw_inventories: dict[str, dict]
) -> dict:
    """Enrich a server entry with HardwareInventory CR data."""
    # Try to match by node name
    hw_name = server["name"].lower().replace(".", "-")
    hw = hw_inventories.get(hw_name)
    if not hw:
        return server

    spec = hw.get("spec", {})
    server["bmcAddress"] = spec.get("bmcAddress", "")
    server["machineProfile"] = spec.get("machineProfile", "")

    interfaces = spec.get("interfaces", [])
    if interfaces:
        server["nics"] = [
            {"name": iface.get("name", f"nic-{i}"), "mac": iface.get("mac", "")}
            for i, iface in enumerate(interfaces)
            if iface.get("mac")
        ]

    # CPU and memory from HW inventory (if populated by discovery)
    if spec.get("cpuCount"):
        server.setdefault("cpu", {})["cores"] = spec["cpuCount"]
    if spec.get("cpuModel"):
        server.setdefault("cpu", {})["model"] = spec["cpuModel"]
    if spec.get("memoryGiB"):
        server["memory"] = f"{spec['memoryGiB']}Gi"

    return server


# ---------------------------------------------------------------------------
# CR generation
# ---------------------------------------------------------------------------

def generate_physical_topology(
    nodes: list[dict],
    hw_inventories: dict[str, dict],
    site_name: str,
    include_hardware: bool = False,
) -> dict:
    """Generate a PhysicalTopology CR from node data."""
    servers = []

    for node in nodes:
        info = classify_node(node)
        server: dict[str, Any] = {
            "name": info["name"],
            "role": info["role"],
            "computeType": info["computeType"],
            "ip": info["internalIP"],
            "ready": info["ready"],
            "arch": info["arch"],
            "os": info["os"],
            "kubeletVersion": info["kubeletVersion"],
            "capacity": info["capacity"],
        }

        if include_hardware:
            server = enrich_with_hardware(server, hw_inventories)

        servers.append(server)

    # Sort: hybrid nodes first (bare metal), then VPC
    servers.sort(key=lambda s: (0 if s.get("computeType") == "hybrid" else 1, s["name"]))

    cr: dict[str, Any] = {
        "apiVersion": "topology.anra.aws.io/v1alpha1",
        "kind": "PhysicalTopology",
        "metadata": {
            "name": site_name,
            "labels": {
                "topology.anra.aws.io/site": site_name,
                "topology.anra.aws.io/generated-by": "generate-topology-cr",
            },
            "annotations": {
                "topology.anra.aws.io/generated-at": datetime.now(timezone.utc).isoformat(),
                "topology.anra.aws.io/node-count": str(len(servers)),
            },
        },
        "spec": {
            "siteName": site_name,
            "servers": servers,
        },
    }

    return cr


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate a PhysicalTopology CR from live cluster state.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--site-name", "-s",
        default=os.getenv("SITE_NAME", ""),
        help="Site name for the CR (default: derived from cluster context)",
    )
    parser.add_argument(
        "--include-hardware", "-hw",
        action="store_true",
        help="Enrich with HardwareInventory CR data (BMC, NICs, CPU)",
    )
    parser.add_argument(
        "--output", "-o",
        default="",
        help="Write output to file instead of stdout",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable debug logging",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s: %(message)s",
    )

    # 1. Get nodes
    logger.info("Querying cluster nodes...")
    nodes = get_nodes()
    if not nodes:
        logger.error("No nodes found. Is kubectl configured correctly?")
        return 1
    logger.info("Found %d node(s)", len(nodes))

    # 2. Derive site name
    site_name = args.site_name
    if not site_name:
        cluster = get_cluster_name()
        # e.g. "site-002-workload" -> "site-002"
        site_name = cluster.rsplit("-", 1)[0] if "-workload" in cluster else cluster
    logger.info("Site name: %s", site_name)

    # 3. Get hardware inventories (optional)
    hw_inventories: dict[str, dict] = {}
    if args.include_hardware:
        logger.info("Querying HardwareInventory CRs...")
        hw_list = get_hardware_inventories()
        hw_inventories = {
            item["metadata"]["name"]: item
            for item in hw_list
            if "metadata" in item
        }
        logger.info("Found %d HardwareInventory CR(s)", len(hw_inventories))

    # 4. Generate CR
    cr = generate_physical_topology(
        nodes=nodes,
        hw_inventories=hw_inventories,
        site_name=site_name,
        include_hardware=args.include_hardware,
    )

    # 5. Output
    yaml_output = yaml.safe_dump(
        cr, default_flow_style=False, allow_unicode=True, sort_keys=False,
    )

    if args.output:
        os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
        with open(args.output, "w") as f:
            f.write(f"# Auto-generated by generate-topology-cr.py\n")
            f.write(f"# Generated: {datetime.now(timezone.utc).isoformat()}\n")
            f.write(f"# Nodes: {len(nodes)}\n")
            f.write(f"---\n")
            f.write(yaml_output)
        logger.info("Written to %s", args.output)
    else:
        sys.stdout.write(yaml_output)

    return 0


if __name__ == "__main__":
    sys.exit(main())
