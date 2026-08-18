# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Tests for alarm rules loaded from config."""

import pytest

from amzn_cse_telco_autonomous_network_agents_app.agent.config import load_config


@pytest.fixture
def alarms():
    return load_config().alarms


@pytest.fixture
def alarm_ref(alarms):
    return {a.name: {"layer": a.layer, "depends_on": a.depends_on, "nf_scope": a.nf_scope} for a in alarms}


class TestSchema:
    def test_alarms_loaded(self, alarms):
        assert len(alarms) >= 2

    def test_all_have_layer(self, alarms):
        for a in alarms:
            assert isinstance(a.layer, int), f"{a.name} missing integer layer"
            assert 0 <= a.layer <= 4, f"{a.name} layer {a.layer} out of range"

    def test_all_have_condition(self, alarms):
        for a in alarms:
            assert a.condition, f"{a.name} missing condition"

    def test_all_have_nf_scope(self, alarms):
        valid = {"per-node", "per-instance", "site-wide"}
        for a in alarms:
            assert a.nf_scope in valid, f"{a.name} invalid nf_scope: {a.nf_scope}"

    def test_depends_on_valid(self, alarms):
        all_names = {a.name for a in alarms}
        for a in alarms:
            for dep in a.depends_on:
                assert dep in all_names, f"{a.name} depends on unknown alarm: {dep}"

    def test_layer_ordering(self, alarm_ref):
        for name, ref in alarm_ref.items():
            for dep in ref["depends_on"]:
                dep_layer = alarm_ref[dep]["layer"]
                assert dep_layer <= ref["layer"], f"{name} (layer {ref['layer']}) depends on {dep} (layer {dep_layer})"

    def test_no_cycles(self, alarm_ref):
        import networkx as nx

        from amzn_cse_telco_autonomous_network_agents_app.agent.correlator import (
            build_graph,
        )

        G = build_graph(alarm_ref)
        assert nx.is_directed_acyclic_graph(G)
