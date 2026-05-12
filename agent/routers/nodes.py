# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

from fastapi import APIRouter, HTTPException
from live_topology import build_live_topology

router = APIRouter(tags=["topology"])


@router.get("/api/nodes")
def get_nodes():
    from topology import get_provider

    topo = get_provider()
    return {"nodes": topo.get_nodes(), "provider": type(topo).__name__}


@router.get("/api/nodes/{node_id}")
def get_node(node_id: str):
    from topology import get_provider

    node = get_provider().get_node(node_id)
    if not node:
        raise HTTPException(404, f"Node {node_id} not found")
    return node


@router.get("/api/nodes/{node_id}/upstream")
def get_upstream(node_id: str):
    from topology import get_provider

    return {"upstream": get_provider().get_upstream(node_id)}


@router.get("/api/nodes/{node_id}/affected")
def get_affected(node_id: str):
    from topology import get_provider

    return {"affected": get_provider().get_affected_by(node_id)}


@router.get("/api/topology")
def get_topology():
    return build_live_topology()
