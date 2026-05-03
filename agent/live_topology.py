# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Live cluster topology discovery (kubectl + config nodes)."""

import logging

from cluster import kubectl_run

log = logging.getLogger(__name__)


def build_live_topology() -> dict:
    """Full topology graph — config nodes + live cluster discovery."""
    from topology import get_provider

    topo = get_provider()
    config_nodes = topo.get_nodes()

    k8s_nodes: list[dict] = []
    nf_pods: list[dict] = []
    edges: list[dict] = []
    try:
        r = kubectl_run(
            [
                "get",
                "nodes",
                "-o",
                "jsonpath={range .items[*]}{.metadata.name},{.metadata.labels.role},{.status.addresses[0].address}\n{end}",
            ],
            timeout=10,
        )
        for line in r.stdout.strip().split("\n"):
            parts = line.split(",")
            if len(parts) >= 3:
                name, role, ip = parts[0], parts[1], parts[2]
                k8s_nodes.append({"name": name, "type": "node", "role": role or "worker", "ip": ip})

        for ns in ["open5gs", "srsran", "anra"]:
            r = kubectl_run(
                [
                    "get",
                    "pods",
                    "-n",
                    ns,
                    "-o",
                    "jsonpath={range .items[*]}{.metadata.name},{.spec.nodeName},{.status.phase}\n{end}",
                ],
                timeout=10,
            )
            for line in r.stdout.strip().split("\n"):
                parts = line.split(",")
                if len(parts) >= 3 and parts[2] == "Running":
                    pod, node = parts[0], parts[1]
                    name_parts = pod.split("-")
                    if pod.startswith("open5gs-"):
                        nf = name_parts[1]
                    elif pod.startswith("ueransim-"):
                        nf = name_parts[1]
                    elif pod.startswith("telegraf-"):
                        nf = "-".join(name_parts[:2])
                    elif ns == "cloudran-agents":
                        nf = "-".join(name_parts[:2])
                    else:
                        nf = name_parts[0]
                    nf_pods.append({"name": f"{ns}/{pod}", "nf": nf, "node": node, "namespace": ns, "type": "nf"})
                    edges.append({"from": f"{ns}/{pod}", "to": node, "type": "runs_on"})
    except Exception as e:
        log.debug("Live topology discovery: %s", e)

    for cn in config_nodes:
        node_match = next((n for n in k8s_nodes if n["ip"] == cn.get("oam_ip")), None)
        if not node_match:
            continue
        for role in cn.get("roles", []):
            virt_id = f"config/{cn['name']}-{role}"
            if not any(p["nf"] == role for p in nf_pods):
                nf_pods.append(
                    {
                        "name": virt_id,
                        "nf": role,
                        "node": node_match["name"],
                        "namespace": "host",
                        "type": "nf",
                    }
                )
                edges.append({"from": virt_id, "to": node_match["name"], "type": "runs_on"})

    nf_pods.append({"name": "ext/ru-antenna", "nf": "ru", "node": "", "namespace": "physical", "type": "nf"})
    nf_pods.append({"name": "ext/sim-ue", "nf": "sim-ue", "node": "", "namespace": "ueransim", "type": "nf"})

    signaling = [
        ("sim-ue", "ru", "Uu"),
        ("ru", "du", "eCPRI"),
        ("du", "cu", "F1"),
        ("cu", "amf", "N2/SCTP"),
        ("amf", "smf", "N11/SBI"),
        ("smf", "upf", "N4/PFCP"),
        ("amf", "ausf", "N12/SBI"),
        ("amf", "nrf", "NRF"),
        ("smf", "nrf", "NRF"),
        ("amf", "nssf", "N22/SBI"),
        ("smf", "pcf", "N7/SBI"),
        ("ausf", "udm", "N13/SBI"),
        ("udm", "udr", "N35/SBI"),
        ("scp", "nrf", "SBI"),
        ("amf", "scp", "SBI"),
    ]
    for src, dst, label in signaling:
        src_pods = [p["name"] for p in nf_pods if p["nf"] == src]
        dst_pods = [p["name"] for p in nf_pods if p["nf"] == dst]
        if src_pods and dst_pods:
            edges.append({"from": src_pods[0], "to": dst_pods[0], "type": label})

    for n in config_nodes:
        for role in n.get("roles", []):
            if role in ("du", "cu"):
                for upstream in topo.get_upstream(n["name"]):
                    edges.append({"from": n["name"], "to": upstream["name"], "type": "connects_to"})

    for n in k8s_nodes:
        n["nf_pod_count"] = sum(1 for p in nf_pods if p.get("node") == n["name"] and p.get("type") == "nf")

    return {
        "provider": type(topo).__name__,
        "config_nodes": config_nodes,
        "k8s_nodes": k8s_nodes,
        "nf_pods": nf_pods,
        "edges": edges,
        "summary": {
            "k8s_node_count": len(k8s_nodes),
            "nf_count": len(nf_pods),
            "edge_count": len(edges),
            "config_node_count": len(config_nodes),
        },
    }
