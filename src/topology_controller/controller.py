"""ANO Topology Controller — computes ImpactMap from Physical/Service topologies."""

import hashlib
import json
import os
from collections import deque
from datetime import datetime, timezone

import kopf
import kubernetes
import networkx as nx

GROUP = "topology.anra.aws.io"
VERSION = "v1alpha1"
NAMESPACE = os.environ.get("WATCH_NAMESPACE", "anra-system")
IMPACT_MAP_PLURAL = "impactmaps"


def _get_api():
    try:
        kubernetes.config.load_incluster_config()
    except kubernetes.config.ConfigException:
        kubernetes.config.load_kube_config()
    return kubernetes.client.CustomObjectsApi()


def _build_graph(api, namespace: str) -> tuple[nx.DiGraph, dict, dict, str]:
    """Build graph from PhysicalTopology and ServiceTopology CRDs."""
    G = nx.DiGraph()
    node_to_nfs: dict[str, list[str]] = {}
    nf_replicas: dict[str, int] = {}
    site_name = ""

    # Physical topology — nodes and physical connections
    phys_list = api.list_namespaced_custom_object(GROUP, VERSION, namespace, "physicaltopologies")
    for pt in phys_list.get("items", []):
        if not site_name:
            site_name = pt.get("spec", {}).get("site", {}).get("name", "")
        for rack in pt.get("spec", {}).get("racks", []):
            for srv in rack.get("servers", []):
                name = srv["name"]
                G.add_node(name, kind="server")
                node_to_nfs.setdefault(name, [])
                for conn in srv.get("connections", []):
                    G.add_edge(name, conn["peer"], layer="physical")
                    G.add_edge(conn["peer"], name, layer="physical")

    # Service topology — NFs and logical connections
    # Supports both schemas:
    #   - Sivani's original: per-NF connections[].peer
    #   - Our mainline: top-level links[] with from/to/interface + per-NF dependsOn[]
    svc_list = api.list_namespaced_custom_object(GROUP, VERSION, namespace, "servicetopologies")
    for st in svc_list.get("items", []):
        for nf in st.get("spec", {}).get("networkFunctions", []):
            nf_name = nf["name"]
            node = nf.get("node", "")
            G.add_node(nf_name, kind="nf", node=node)
            nf_replicas[nf_name] = nf.get("replicas", 1)
            if node:
                node_to_nfs.setdefault(node, []).append(nf_name)
                G.add_edge(node, nf_name, layer="hosts")
            # Schema A: per-NF connections (Sivani's format)
            for conn in nf.get("connections", []):
                G.add_edge(
                    nf_name,
                    conn["peer"],
                    layer="logical",
                    protocol=conn.get("protocol"),
                )
            # Schema B: per-NF dependsOn (our mainline format)
            for dep in nf.get("dependsOn", []):
                G.add_edge(nf_name, dep, layer="logical")

        # Schema B: top-level links[] (our mainline format)
        for link in st.get("spec", {}).get("links", []):
            src, dst = link.get("from", ""), link.get("to", "")
            if src and dst:
                G.add_edge(src, dst, layer="logical", protocol=link.get("interface", ""))

    return G, node_to_nfs, nf_replicas, site_name


def _cascade_chain(G: nx.DiGraph, start: str, max_depth: int = 6) -> list[str]:
    """BFS from failed node, return ordered chain of affected nodes."""
    visited, queue, chain = {start}, deque([(start, 0)]), []
    while queue:
        node, depth = queue.popleft()
        if depth > max_depth:
            break
        for succ in sorted(G.successors(node)):
            if succ not in visited:
                visited.add(succ)
                chain.append(succ)
                queue.append((succ, depth + 1))
    return chain


def _severity(affected_nfs: list[dict]) -> str:
    count = len(affected_nfs)
    if count >= 4:
        return "Critical"
    if count >= 2:
        return "High"
    return "Medium"


def _compute_impact(api, namespace: str) -> dict:
    G, node_to_nfs, nf_replicas, site_name = _build_graph(api, namespace)
    servers = [n for n, d in G.nodes(data=True) if d.get("kind") == "server"]
    nf_nodes = [n for n, d in G.nodes(data=True) if d.get("kind") == "nf"]

    # Connectivity SPOFs via articulation points on physical-layer only
    phys_edges = [(u, v) for u, v, d in G.edges(data=True) if d.get("layer") == "physical"]
    phys_graph = nx.Graph(phys_edges)
    art_points = set(nx.articulation_points(phys_graph)) & set(servers)

    # Per-node impact
    nodes_status = []
    for srv in sorted(servers):
        hosted = sorted(node_to_nfs.get(srv, []))
        hosted_set = set(hosted)
        # Blast radius: remove server and all NFs it hosts from the graph
        G_copy = G.copy()
        G_copy.remove_node(srv)
        for down_nf in hosted_set:
            if down_nf in G_copy:
                G_copy.remove_node(down_nf)
        affected = []
        for nf in nf_nodes:
            if nf in hosted_set:
                affected.append({"name": nf, "impact": "down", "reason": f"hosted on {srv}"})
            elif nf in G_copy and not any(nx.has_path(G_copy, s, nf) for s in servers if s != srv and s in G_copy):
                affected.append(
                    {
                        "name": nf,
                        "impact": "unreachable",
                        "reason": f"no path after {srv} removal",
                    }
                )
        has_failover = srv not in art_points and all(nf_replicas.get(nf, 1) > 1 for nf in hosted)
        reason = "not an articulation point and replicas > 1" if has_failover else "single point or single replica"
        nodes_status.append(
            {
                "name": srv,
                "hostedNFs": hosted,
                "impactIfDown": {
                    "affectedNFs": sorted(affected, key=lambda x: x["name"]),
                    "severity": _severity(affected),
                },
                "redundancy": {"hasFailover": has_failover, "reason": reason},
            }
        )

    # Capacity SPOFs: nodes where ALL hosted NFs have replicas=1
    capacity_spofs = []
    for srv in sorted(servers):
        hosted = node_to_nfs.get(srv, [])
        if hosted and all(nf_replicas.get(nf, 1) == 1 for nf in hosted):
            capacity_spofs.append(
                {
                    "node": srv,
                    "nfs": sorted(hosted),
                    "reason": "all NFs single-replica",
                    "remediation": "increase replicas or spread across nodes",
                }
            )

    connectivity_spofs = [
        {
            "node": s,
            "reason": "articulation point in physical graph",
            "remediation": "add redundant link",
        }
        for s in sorted(art_points)
    ]

    # Cascade chains
    cascades = [{"trigger": srv, "chain": _cascade_chain(G, srv)} for srv in sorted(servers)]

    completeness = "full" if nf_nodes else "physical-only"

    status = {
        "lastReconciled": datetime.now(timezone.utc).isoformat(),
        "completeness": completeness,
        "site": {
            "name": site_name,
            "totalNodes": len(servers),
            "totalNFs": len(nf_nodes),
        },
        "nodes": nodes_status,
        "singlePointsOfFailure": {
            "connectivity": connectivity_spofs,
            "capacity": capacity_spofs,
        },
        "cascadeChains": cascades,
    }
    hash_payload = {k: v for k, v in status.items() if k != "lastReconciled"}
    status["graphHash"] = hashlib.sha256(json.dumps(hash_payload, sort_keys=True, default=str).encode()).hexdigest()[:16]
    return status


def _reconcile(namespace: str, **_):
    api = _get_api()
    status = _compute_impact(api, namespace)
    # Ensure ImpactMap exists
    try:
        existing = api.get_namespaced_custom_object(GROUP, VERSION, namespace, IMPACT_MAP_PLURAL, "site-impact")
        old_hash = existing.get("status", {}).get("graphHash", "")
        if old_hash == status["graphHash"]:
            return
    except kubernetes.client.exceptions.ApiException as e:
        if e.status == 404:
            api.create_namespaced_custom_object(
                GROUP,
                VERSION,
                namespace,
                IMPACT_MAP_PLURAL,
                {
                    "apiVersion": f"{GROUP}/{VERSION}",
                    "kind": "ImpactMap",
                    "metadata": {"name": "site-impact", "namespace": namespace},
                    "spec": {
                        "siteRef": status["site"]["name"],
                        "reconcileIntervalSeconds": 60,
                    },
                },
            )
        else:
            raise
    api.patch_namespaced_custom_object_status(GROUP, VERSION, namespace, IMPACT_MAP_PLURAL, "site-impact", {"status": status})


@kopf.on.create(GROUP, VERSION, "physicaltopologies")
@kopf.on.update(GROUP, VERSION, "physicaltopologies")
@kopf.on.create(GROUP, VERSION, "servicetopologies")
@kopf.on.update(GROUP, VERSION, "servicetopologies")
def on_topology_change(namespace, **kwargs):
    _reconcile(namespace)


@kopf.on.timer(GROUP, VERSION, "impactmaps", interval=60, idle=60)
def on_timer(namespace, **kwargs):
    _reconcile(namespace)
