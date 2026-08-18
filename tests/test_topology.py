# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Tests for topology.py — YamlTopology provider."""
from pathlib import Path


import amzn_cse_telco_autonomous_network_agents_app.agent.topology as topology

class TestYamlTopology:
    def setup_method(self):
        topology._provider = None

    def test_get_provider_returns_yaml(self):
        p = topology.get_provider()
        assert isinstance(p, topology.YamlTopology)

    def test_get_nodes(self):
        p = topology.get_provider()
        nodes = p.get_nodes()
        assert len(nodes) == 2
        assert all("name" in n for n in nodes)

    def test_get_node_by_name(self):
        p = topology.get_provider()
        n = p.get_node("worker-1")
        assert n is not None
        assert n["oam_ip"] == "192.168.31.195"

    def test_get_node_by_ssm(self):
        p = topology.get_provider()
        n = p.get_node("mi-aaa")
        assert n is not None
        assert n["name"] == "worker-1"

    def test_get_node_by_oam_ip(self):
        p = topology.get_provider()
        n = p.get_node("192.168.31.222")
        assert n is not None
        assert n["name"] == "worker-2"

    def test_get_node_not_found(self):
        p = topology.get_provider()
        assert p.get_node("nonexistent") is None

    def test_get_node_by_role(self):
        p = topology.get_provider()
        nodes = p.get_node_by_role("du")
        assert len(nodes) == 1
        assert nodes[0]["name"] == "worker-2"

    def test_get_node_by_role_upf(self):
        p = topology.get_provider()
        nodes = p.get_node_by_role("upf")
        assert len(nodes) == 1
        assert nodes[0]["name"] == "worker-1"

    def test_get_upstream_du_returns_core(self):
        p = topology.get_provider()
        upstream = p.get_upstream("worker-2")
        # DU/CU should have upstream to UPF nodes
        assert len(upstream) >= 1

    def test_get_upstream_unknown_returns_empty(self):
        p = topology.get_provider()
        assert p.get_upstream("nonexistent") == []

    def test_get_downstream_upf_returns_ran(self):
        p = topology.get_provider()
        downstream = p.get_downstream("worker-1")
        assert len(downstream) >= 1

    def test_get_affected_by(self):
        p = topology.get_provider()
        affected = p.get_affected_by("worker-1")
        assert len(affected) == 2  # flat topology returns all

    def test_node_dict_has_bmc(self):
        p = topology.get_provider()
        n = p.get_node("worker-1")
        assert "bmc_ip" in n
        assert n["bmc_ip"] == "192.168.30.10"

    def test_provider_cached(self):
        p1 = topology.get_provider()
        p2 = topology.get_provider()
        assert p1 is p2
