# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Tests for correlator.py — dependency graph, rule-based correlation, RCA."""
import time
from unittest.mock import MagicMock, patch

import pytest

import amzn_cse_telco_autonomous_network_agents_app.agent.correlator as correlator
from amzn_cse_telco_autonomous_network_agents_app.agent.correlator import (
    build_graph,
    correlate,
    correlate_batch,
    rca_investigate,
)


@pytest.fixture(autouse=True)
def reset_graph():
    correlator._graph = None
    yield
    correlator._graph = None


@pytest.fixture
def alarm_ref():
    from amzn_cse_telco_autonomous_network_agents_app.agent.config import load_config
    cfg = load_config()
    return {a.name: {"layer": a.layer, "depends_on": a.depends_on, "nf_scope": a.nf_scope,
                      "severity": a.severity} for a in cfg.alarms}


def make_event(name, layer=2, node="", ts_offset=0):
    return {"ts": time.time() - ts_offset, "name": name, "severity": "critical",
            "layer": layer, "source": "influxdb", "node": node, "nf": "", "value": 0}


@pytest.fixture
def mock_topology():
    tp = MagicMock()
    tp.get_upstream.return_value = [{"name": "worker-1"}]
    tp.get_affected_by.return_value = [{"name": "worker-1"}, {"name": "worker-2"}]
    return tp


class TestBuildGraph:
    def test_has_all_alarms(self, alarm_ref):
        G = build_graph(alarm_ref)
        for name in alarm_ref:
            assert name in G.nodes

    def test_edges_match_depends_on(self, alarm_ref):
        G = build_graph(alarm_ref)
        for name, ref in alarm_ref.items():
            for dep in ref.get("depends_on", []):
                assert G.has_edge(dep, name), f"Missing edge {dep} → {name}"

    def test_no_cycles(self, alarm_ref):
        import networkx as nx
        G = build_graph(alarm_ref)
        assert nx.is_directed_acyclic_graph(G)


class TestCorrelateSingle:
    def test_single_alarm_execute(self, alarm_ref):
        alarm = {"name": "du_timing_failure", "severity": "critical", "source": "influxdb"}
        result = correlate(alarm, [], alarm_ref)
        assert result["action"] == "execute"
        assert result["confidence"] == "high"

    def test_single_alarm_is_root(self, alarm_ref):
        alarm = {"name": "du_timing_failure", "severity": "critical", "source": "influxdb"}
        result = correlate(alarm, [], alarm_ref)
        assert result["root_cause"] == "du_timing_failure"


class TestTopologyFiltering:
    def test_same_node_correlated(self, alarm_ref):
        alarm = {"name": "du_timing_failure", "severity": "critical", "source": "influxdb", "node_name": "w1"}
        recent = [make_event("ptp_drift", layer=1, node="w1", ts_offset=10)]
        result = correlate(alarm, recent, alarm_ref)
        assert result["action"] == "suppress"

    def test_different_node_not_correlated(self, alarm_ref):
        alarm = {"name": "du_timing_failure", "severity": "critical", "source": "influxdb", "node_name": "w1"}
        recent = [make_event("ptp_drift", layer=1, node="w2", ts_offset=10)]
        result = correlate(alarm, recent, alarm_ref)
        # ptp_drift is per-node scope, different node → not related → execute
        assert result["action"] == "execute"

    def test_site_wide_always_correlates(self, alarm_ref):
        alarm = {"name": "amf_gnb_disconnect", "severity": "critical", "source": "influxdb", "node_name": "w1"}
        recent = [make_event("network_partition", layer=1, node="w2", ts_offset=10)]
        result = correlate(alarm, recent, alarm_ref)
        assert result["action"] == "suppress"

    def test_no_topology_assumes_related(self, alarm_ref):
        alarm = {"name": "amf_gnb_disconnect", "severity": "critical", "source": "influxdb"}
        recent = [make_event("network_partition", layer=1, ts_offset=10)]
        result = correlate(alarm, recent, alarm_ref, topology=None)
        assert result["action"] == "suppress"


class TestTieredWindows:
    def test_same_layer_within_window(self, alarm_ref):
        alarm = {"name": "amf_gnb_disconnect", "severity": "critical", "source": "influxdb"}
        recent = [make_event("nf_crashloop", layer=2, ts_offset=25)]
        result = correlate(alarm, recent, alarm_ref)
        assert result["action"] == "suppress"

    def test_same_layer_outside_window(self, alarm_ref):
        alarm = {"name": "amf_gnb_disconnect", "severity": "critical", "source": "influxdb"}
        recent = [make_event("nf_crashloop", layer=2, ts_offset=35)]
        result = correlate(alarm, recent, alarm_ref)
        assert result["action"] == "execute"

    def test_cross_layer_wider_window(self, alarm_ref):
        # du_timing(L3) + network_partition(L1): window = 30 * abs(3-1) = 60s
        alarm = {"name": "du_timing_failure", "severity": "critical", "source": "influxdb", "node_name": "w1"}
        recent = [make_event("network_partition", layer=1, node="w1", ts_offset=55)]
        result = correlate(alarm, recent, alarm_ref)
        assert result["action"] == "suppress"

    def test_cross_layer_outside_window(self, alarm_ref):
        # du_timing(L3) + network_partition(L1): window = 60s, 65s is outside
        alarm = {"name": "du_timing_failure", "severity": "critical", "source": "influxdb", "node_name": "w1"}
        recent = [make_event("network_partition", layer=1, node="w1", ts_offset=65)]
        result = correlate(alarm, recent, alarm_ref)
        assert result["action"] == "execute"


class TestSuppression:
    def test_symptom_suppressed(self, alarm_ref):
        alarm = {"name": "du_timing_failure", "severity": "critical", "source": "influxdb", "node_name": "w1"}
        recent = [make_event("ptp_drift", layer=1, node="w1", ts_offset=10)]
        result = correlate(alarm, recent, alarm_ref)
        assert result["action"] == "suppress"
        assert result["root_cause"] == "ptp_drift"

    def test_root_cause_executes(self, alarm_ref):
        alarm = {"name": "ptp_drift", "severity": "critical", "source": "influxdb", "node_name": "w1"}
        recent = [make_event("du_timing_failure", layer=3, node="w1", ts_offset=5)]
        result = correlate(alarm, recent, alarm_ref)
        assert result["action"] == "execute"
        assert "du_timing_failure" in result["symptoms"]

    def test_reeval_populated(self, alarm_ref):
        alarm = {"name": "du_timing_failure", "severity": "critical", "source": "influxdb", "node_name": "w1"}
        recent = [make_event("ptp_drift", layer=1, node="w1", ts_offset=10)]
        result = correlate(alarm, recent, alarm_ref)
        assert "du_timing_failure" in result["reeval"]

    def test_not_suppressed_no_path(self, alarm_ref):
        alarm = {"name": "du_cpu_overload", "severity": "critical", "source": "influxdb"}
        recent = [make_event("upf_pfcp_loss", layer=2, ts_offset=10)]
        result = correlate(alarm, recent, alarm_ref)
        # No dependency path between du_cpu_overload and upf_pfcp_loss
        assert result["action"] != "suppress" or result["root_cause"] != "upf_pfcp_loss"


class TestBatch:
    def test_lowest_layer_root(self, alarm_ref):
        alarms = [
            {"name": "du_timing_failure", "severity": "critical"},
            {"name": "network_partition", "severity": "critical"},
            {"name": "amf_gnb_disconnect", "severity": "critical"},
        ]
        result = correlate_batch(alarms, [], alarm_ref)
        assert result["root_cause"] == "network_partition"
        assert "du_timing_failure" in result["symptoms"]

    def test_batch_returns_symptoms(self, alarm_ref):
        alarms = [
            {"name": "du_timing_failure", "severity": "critical"},
            {"name": "ptp_drift", "severity": "critical"},
        ]
        result = correlate_batch(alarms, [], alarm_ref)
        assert len(result["symptoms"]) == 1

    def test_empty_batch(self, alarm_ref):
        result = correlate_batch([], [], alarm_ref)
        assert result["action"] == "execute"


class TestEscalation:
    def test_unrelated_escalates(self, alarm_ref):
        alarm = {"name": "du_cpu_overload", "severity": "critical", "source": "influxdb"}
        recent = [make_event("sbi_mesh_failure", layer=2, ts_offset=10)]
        result = correlate(alarm, recent, alarm_ref)
        # sbi_mesh_failure is not in du_cpu_overload's depends_on, and du_cpu_overload
        # is not ancestor of sbi_mesh_failure → escalate
        assert result["action"] in ("escalate", "execute")


class TestRCAAgent:
    @patch("amzn_cse_telco_autonomous_network_agents_app.agent.correlator._create_rca_agent")
    def test_rca_returns_valid(self, mock_create, alarm_ref):
        mock_agent = MagicMock()
        mock_agent.return_value = '{"root_cause": "ptp_drift", "reasoning": "timing", "confidence": "high"}'
        mock_create.return_value = mock_agent
        events = [make_event("du_timing_failure"), make_event("ptp_drift")]
        result = rca_investigate(events, alarm_ref)
        assert result["root_cause"] == "ptp_drift"

    def test_rca_failure_fallback(self, alarm_ref):
        with patch("amzn_cse_telco_autonomous_network_agents_app.agent.correlator._create_rca_agent", side_effect=Exception("no bedrock")):
            events = [make_event("du_timing_failure", layer=3), make_event("ptp_drift", layer=1)]
            result = rca_investigate(events, alarm_ref)
            assert result["root_cause"] == "ptp_drift"  # lowest layer fallback
            assert result["confidence"] == "low"
