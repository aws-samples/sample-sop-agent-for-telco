#!/usr/bin/env python3
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Generate unified agent-config.yaml and Helm values overlay from a site descriptor.

Usage:
    python generate-site-config.py configs/site-descriptors/docomo-site-002.yaml -o output/
    python generate-site-config.py configs/site-descriptors/sjc38.yaml -o output/ --check-connectivity

Part of CSE-2997: site descriptor schema and config generation pipeline.
"""

import argparse
import sys
from pathlib import Path

import yaml


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

REQUIRED_FIELDS = [
    ("site", "name"),
    ("site", "cluster"),
    ("site", "region"),
    ("images", "registry"),
    ("aws", "bedrockRoleArn"),
]

REQUIRED_HARDWARE_NODE_FIELDS = ["name", "bmc_ip", "oam_ip", "roles"]


def validate_descriptor(descriptor: dict) -> list[str]:
    """Validate a site descriptor dict. Returns list of error messages (empty = valid)."""
    errors: list[str] = []

    for section, field in REQUIRED_FIELDS:
        section_data = descriptor.get(section)
        if not section_data:
            errors.append(f"Missing required section: {section}")
            continue
        if not section_data.get(field):
            errors.append(f"Missing required field: {section}.{field}")

    # Validate hardware.nodes if hardware section exists
    hardware = descriptor.get("hardware") or {}
    nodes = hardware.get("nodes", [])
    if nodes:
        for i, node in enumerate(nodes):
            for nf in REQUIRED_HARDWARE_NODE_FIELDS:
                if not node.get(nf):
                    errors.append(
                        f"Missing required field in hardware.nodes[{i}]: {nf}"
                    )

    return errors


# ---------------------------------------------------------------------------
# Config Generation
# ---------------------------------------------------------------------------


def generate_agent_config(descriptor: dict) -> dict:
    """Transform a site descriptor into the unified agent-config.yaml format (CSE-2977)."""
    site = descriptor.get("site") or {}
    hardware = descriptor.get("hardware") or {}
    monitoring = descriptor.get("monitoring") or {}
    network = descriptor.get("network") or {}

    config: dict = {
        "version": "1",
        "cluster": {
            "name": site.get("cluster", ""),
            "region": site.get("region", "us-west-1"),
        },
        "bedrock": {
            "region": "us-west-2",
            "model_tier": "smart",
        },
        "monitoring": {
            "influxdb_url": monitoring.get("influxdb_url", ""),
            "influxdb_org": monitoring.get("influxdb_org", "srs"),
            "influxdb_bucket": monitoring.get("influxdb_bucket", "srsran"),
            "alertmanager_url": monitoring.get("alertmanager_url", ""),
        },
        "topology": {
            "provider": "yaml",
        },
        "approval": {
            "mode": "auto",
        },
        "provisioning": {
            "tinkerbell_namespace": "tink-system",
        },
        "deployment": {
            "helm_repo": "",
            "gitops_repo": "",
            "gitops_branch": "main",
        },
    }

    # Map hardware.nodes to config nodes
    nodes = []
    for node in hardware.get("nodes", []):
        config_node = {
            "name": node.get("name", ""),
            "oam_ip": node.get("oam_ip", ""),
            "bmc": {
                "ip": node.get("bmc_ip", ""),
                "type": node.get("bmc_type", "idrac"),
            },
            "roles": node.get("roles", []),
        }
        nodes.append(config_node)
    config["nodes"] = nodes

    # Add cluster context if namespace provided
    if site.get("namespace"):
        config["cluster"]["context"] = f"{site['cluster']}"

    return config


def generate_helm_values(descriptor: dict) -> dict:
    """Generate a Helm values overlay for the site."""
    site = descriptor.get("site") or {}
    images = descriptor.get("images") or {}
    hardware = descriptor.get("hardware") or {}
    monitoring = descriptor.get("monitoring") or {}
    scaling = descriptor.get("scaling") or {}
    aws = descriptor.get("aws") or {}

    values: dict = {
        "image": {
            "repository": images.get("registry", ""),
            "tag": images.get("tag", images.get("service_tag", "latest")),
            "pullPolicy": "Always",
        },
        "config": {
            "cluster": {
                "name": site.get("cluster", ""),
                "region": site.get("region", ""),
            },
        },
        "monitoring": {
            "influxdbUrl": monitoring.get("influxdb_url", ""),
            "alertmanagerUrl": monitoring.get("alertmanager_url", ""),
        },
    }

    # IRSA annotation for AWS credentials (Bedrock, CloudWatch, SSM)
    bedrock_role = aws.get("bedrockRoleArn", "")
    if bedrock_role:
        values["serviceAccount"] = {
            "create": True,
            "annotations": {
                "eks.amazonaws.com/role-arn": bedrock_role,
            },
        }

    # Add node selector if affinity label provided
    if hardware.get("node_affinity_label"):
        label_parts = hardware["node_affinity_label"].split("=", 1)
        if len(label_parts) == 2:
            values["nodeSelector"] = {label_parts[0]: label_parts[1]}
        else:
            values["nodeSelector"] = {hardware["node_affinity_label"]: "true"}

    # Add image pull secret
    if images.get("pull_secret"):
        values["imagePullSecrets"] = [{"name": images["pull_secret"]}]

    # Add scaling config
    if scaling:
        values["replicaCount"] = scaling.get("service_pod_count", 1)

    # Add resources if specified
    if hardware.get("cpu_per_service_pod") or hardware.get("memory_per_service_pod"):
        values["resources"] = {
            "requests": {},
            "limits": {},
        }
        if hardware.get("cpu_per_service_pod"):
            values["resources"]["requests"]["cpu"] = hardware["cpu_per_service_pod"]
            values["resources"]["limits"]["cpu"] = hardware["cpu_per_service_pod"]
        if hardware.get("memory_per_service_pod"):
            values["resources"]["requests"]["memory"] = hardware["memory_per_service_pod"]
            values["resources"]["limits"]["memory"] = hardware["memory_per_service_pod"]

    return values


# ---------------------------------------------------------------------------
# Connectivity Check (stub)
# ---------------------------------------------------------------------------


def check_connectivity(descriptor: dict) -> bool:
    """Stub: verify network connectivity to site endpoints.

    Future implementation will ping BMC IPs, verify InfluxDB/Alertmanager
    reachability, and validate K8s API access.
    """
    print("[check-connectivity] Stub: connectivity validation not yet implemented.")
    print(f"  Would check: {len(descriptor.get('hardware', {}).get('nodes', []))} node BMC IPs")
    monitoring = descriptor.get("monitoring") or {}
    if monitoring.get("influxdb_url"):
        print(f"  Would check: InfluxDB at {monitoring['influxdb_url']}")
    if monitoring.get("alertmanager_url"):
        print(f"  Would check: Alertmanager at {monitoring['alertmanager_url']}")
    return True


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate unified agent-config and Helm values from a site descriptor."
    )
    parser.add_argument(
        "descriptor",
        type=str,
        help="Path to site descriptor YAML file",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=str,
        default=".",
        help="Output directory for generated files (default: current directory)",
    )
    parser.add_argument(
        "--check-connectivity",
        action="store_true",
        help="Run connectivity checks against site endpoints (stub)",
    )

    args = parser.parse_args()

    # Load descriptor
    descriptor_path = Path(args.descriptor)
    if not descriptor_path.exists():
        print(f"Error: site descriptor not found: {descriptor_path}", file=sys.stderr)
        return 1

    with open(descriptor_path) as f:
        descriptor = yaml.safe_load(f)

    if not descriptor:
        print(f"Error: site descriptor is empty: {descriptor_path}", file=sys.stderr)
        return 1

    # Validate
    errors = validate_descriptor(descriptor)
    if errors:
        print("Error: site descriptor validation failed:", file=sys.stderr)
        for err in errors:
            print(f"  - {err}", file=sys.stderr)
        return 1

    # Optional connectivity check
    if args.check_connectivity:
        check_connectivity(descriptor)

    # Generate outputs
    site_name = descriptor["site"]["name"]
    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Generate agent-config.yaml
    agent_config = generate_agent_config(descriptor)
    agent_config_path = output_dir / "agent-config.yaml"
    with open(agent_config_path, "w") as f:
        yaml.dump(agent_config, f, default_flow_style=False, sort_keys=False)
    print(f"Generated: {agent_config_path}")

    # Generate values-<site-name>.yaml
    helm_values = generate_helm_values(descriptor)
    values_path = output_dir / f"values-{site_name}.yaml"
    with open(values_path, "w") as f:
        yaml.dump(helm_values, f, default_flow_style=False, sort_keys=False)
    print(f"Generated: {values_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
