# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Topology Provider — abstraction layer for node/NF topology.

Today: reads anra-config.yaml (single-site, flat node list)
Scale: swap to NeptuneTopology for multi-site graph traversal

The monitor, executor, and dashboard all call topology.get_provider()
and use the same interface regardless of backend.
"""

import logging
from abc import ABC, abstractmethod

from config import NodeConfig, load_config

logger = logging.getLogger(__name__)


class TopologyProvider(ABC):
    """Interface for topology queries. Implement for each backend."""

    @abstractmethod
    def get_node(self, node_id: str) -> dict | None:
        """Get node by SSM ID, OAM IP, or name."""

    @abstractmethod
    def get_nodes(self) -> list[dict]:
        """List all nodes."""

    @abstractmethod
    def get_upstream(self, node_id: str) -> list[dict]:
        """Get components upstream of this node (e.g., CU → Core)."""

    @abstractmethod
    def get_downstream(self, node_id: str) -> list[dict]:
        """Get components downstream (e.g., Core → DU)."""

    @abstractmethod
    def get_affected_by(self, component_id: str) -> list[dict]:
        """Get all nodes/NFs affected if this component fails."""

    @abstractmethod
    def get_node_by_role(self, role: str) -> list[dict]:
        """Get nodes by role (du, cu, upf, etc.)."""


class YamlTopology(TopologyProvider):
    """Single-site topology from anra-config.yaml."""

    def __init__(self):
        self.config = load_config()

    def _node_to_dict(self, n: NodeConfig) -> dict:
        return {
            "name": n.name,
            "oam_ip": n.oam_ip,
            "ssm_id": n.ssm_id,
            "roles": n.roles,
            "namespaces": n.namespaces,
            "bmc_ip": n.bmc.ip,
            "bmc_type": n.bmc.type,
        }

    def get_node(self, node_id: str) -> dict | None:
        for n in self.config.nodes:
            if node_id in (n.name, n.ssm_id, n.oam_ip, n.bmc.ip):
                return self._node_to_dict(n)
        return None

    def get_nodes(self) -> list[dict]:
        return [self._node_to_dict(n) for n in self.config.nodes]

    def get_upstream(self, node_id: str) -> list[dict]:
        # Flat topology: DU/CU → Core (region nodes)
        node = self.get_node(node_id)
        if not node:
            return []
        if any(r in node["roles"] for r in ["du", "cu"]):
            return [n for n in self.get_nodes() if "upf" in n["roles"] or not n["roles"]]
        return []

    def get_downstream(self, node_id: str) -> list[dict]:
        node = self.get_node(node_id)
        if not node:
            return []
        if "upf" in node["roles"]:
            return [n for n in self.get_nodes() if any(r in n["roles"] for r in ["du", "cu"])]
        return []

    def get_affected_by(self, component_id: str) -> list[dict]:
        # In flat topology, all nodes are potentially affected
        return self.get_nodes()

    def get_node_by_role(self, role: str) -> list[dict]:
        return [self._node_to_dict(n) for n in self.config.nodes if role in n.roles]


class NeptuneTopology(TopologyProvider):
    """Multi-site topology from Amazon Neptune. Drop-in replacement for YamlTopology.

    Requires: pip install gremlinpython
    Config: topology.endpoint in anra-config.yaml
    """

    def __init__(self, endpoint: str):
        self.endpoint = endpoint
        self._g = None
        logger.info(f"Neptune topology: {endpoint}")

    def _connect(self):
        if not self._g:
            from gremlin_python.driver.driver_remote_connection import DriverRemoteConnection
            from gremlin_python.process.anonymous_traversal import traversal

            conn = DriverRemoteConnection(f"wss://{self.endpoint}:8182/gremlin", "g")
            self._g = traversal().withRemote(conn)
        return self._g

    def get_node(self, node_id: str) -> dict | None:
        g = self._connect()
        results = g.V().has("id", node_id).valueMap(True).toList()
        return self._to_dict(results[0]) if results else None

    def get_nodes(self) -> list[dict]:
        g = self._connect()
        return [self._to_dict(v) for v in g.V().hasLabel("node").valueMap(True).toList()]

    def get_upstream(self, node_id: str) -> list[dict]:
        g = self._connect()
        return [self._to_dict(v) for v in g.V().has("id", node_id).out("connects_to").valueMap(True).toList()]

    def get_downstream(self, node_id: str) -> list[dict]:
        g = self._connect()
        return [self._to_dict(v) for v in g.V().has("id", node_id).in_("connects_to").valueMap(True).toList()]

    def get_affected_by(self, component_id: str) -> list[dict]:
        g = self._connect()
        # Traverse all paths through this component
        return [self._to_dict(v) for v in g.V().has("id", component_id).both().both().dedup().valueMap(True).toList()]

    def get_node_by_role(self, role: str) -> list[dict]:
        g = self._connect()
        return [self._to_dict(v) for v in g.V().has("role", role).valueMap(True).toList()]

    @staticmethod
    def _to_dict(vertex_map: dict) -> dict:
        return {
            k: v[0] if isinstance(v, list) and len(v) == 1 else v
            for k, v in vertex_map.items()
            if k != "T.id" and k != "T.label"
        }


# ── Factory ──

_provider: TopologyProvider | None = None


def get_provider() -> TopologyProvider:
    """Get the configured topology provider. Cached after first call."""
    global _provider
    if _provider:
        return _provider
    cfg = load_config()
    if cfg.topology_provider == "neptune" and cfg.neptune_endpoint:
        _provider = NeptuneTopology(cfg.neptune_endpoint)
    else:
        _provider = YamlTopology()
    logger.info(f"Topology provider: {type(_provider).__name__}")
    return _provider
