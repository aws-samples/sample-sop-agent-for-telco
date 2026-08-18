# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Unit tests for ANDA orchestrator logic and config parsing.

Tests pure functions only — no strands dependency, no subprocess calls.
"""
from __future__ import annotations

import yaml

from amzn_cse_telco_autonomous_network_agents_app.agent.agents.anda.config import (
    NFCatalogEntry,
    UpgradeStrategy,
    get_catalog_entry,
    get_strategy_for_nf,
    load_nf_catalog,
    load_upgrade_strategy,
)

# ---------------------------------------------------------------------------
# NF Catalog loading
# ---------------------------------------------------------------------------


class TestNFCatalog:
    """Tests for NF catalog loading and querying."""

    def test_load_catalog_from_yaml(self, tmp_path):
        catalog_file = tmp_path / "catalog.yaml"
        catalog_file.write_text(yaml.dump({"nfs": [
            {"name": "srsran", "chart": "oci://registry/srsran", "version": "24.10", "namespace": "ran"},
            {"name": "open5gs", "chart": "oci://registry/open5gs", "version": "2.7", "namespace": "core"},
        ]}))
        entries = load_nf_catalog(str(catalog_file))
        assert len(entries) == 2
        assert entries[0].name == "srsran"
        assert entries[0].namespace == "ran"
        assert entries[1].version == "2.7"

    def test_load_catalog_empty_file(self, tmp_path):
        catalog_file = tmp_path / "catalog.yaml"
        catalog_file.write_text("")
        entries = load_nf_catalog(str(catalog_file))
        assert entries == []

    def test_load_catalog_missing_file(self):
        entries = load_nf_catalog("/nonexistent/path/catalog.yaml")
        assert entries == []

    def test_get_catalog_entry_found(self):
        catalog = [
            NFCatalogEntry(name="amf", chart="oci://amf", version="2.7", namespace="core"),
            NFCatalogEntry(name="srsran", chart="oci://srsran", version="24.10", namespace="ran"),
        ]
        entry = get_catalog_entry(catalog, "srsran")
        assert entry is not None
        assert entry.chart == "oci://srsran"

    def test_get_catalog_entry_not_found(self):
        catalog = [NFCatalogEntry(name="amf", chart="c", version="1", namespace="core")]
        entry = get_catalog_entry(catalog, "nonexistent")
        assert entry is None

    def test_get_catalog_entry_case_insensitive(self):
        catalog = [NFCatalogEntry(name="Open5GS", chart="c", version="1", namespace="core")]
        entry = get_catalog_entry(catalog, "open5gs")
        assert entry is not None


# ---------------------------------------------------------------------------
# Upgrade strategy loading
# ---------------------------------------------------------------------------


class TestUpgradeStrategy:
    """Tests for upgrade strategy loading and matching."""

    def test_load_strategies_from_yaml(self, tmp_path):
        strat_file = tmp_path / "upgrade-strategy.yaml"
        strat_file.write_text(yaml.dump({"strategies": [
            {"name": "core-stateful", "appliesTo": ["open5gs-amf", "open5gs-smf"], "steps": [
                {"name": "drain", "action": "signal-amf-deregistration"},
                {"name": "deploy", "action": "patch-argocd-application"},
            ]},
            {"name": "stateless", "appliesTo": ["open5gs-nrf"], "steps": [
                {"name": "deploy", "action": "patch-argocd-application"},
            ]},
        ]}))
        strategies = load_upgrade_strategy(str(strat_file))
        assert len(strategies) == 2
        assert strategies[0].name == "core-stateful"
        assert "open5gs-amf" in strategies[0].applies_to
        assert len(strategies[0].steps) == 2

    def test_load_strategies_missing_file(self):
        strategies = load_upgrade_strategy("/nonexistent/path.yaml")
        assert strategies == []

    def test_get_strategy_for_nf_match(self):
        strategies = [
            UpgradeStrategy(name="core-stateful", applies_to=["open5gs-amf", "open5gs-smf"], steps=[]),
            UpgradeStrategy(name="ran", applies_to=["srsran-gnb"], steps=[]),
        ]
        result = get_strategy_for_nf(strategies, "open5gs-amf")
        assert result is not None
        assert result.name == "core-stateful"

    def test_get_strategy_for_nf_no_match(self):
        strategies = [
            UpgradeStrategy(name="core-stateful", applies_to=["open5gs-amf"], steps=[]),
        ]
        result = get_strategy_for_nf(strategies, "unknown-nf")
        assert result is None


# ---------------------------------------------------------------------------
# NF dependency ordering
# ---------------------------------------------------------------------------


class TestNFOrdering:
    """Tests for 3GPP NF dependency order resolution."""

    def test_canonical_order(self):
        """NFs should be sorted in 3GPP startup dependency order."""
        # Import the private function — it's pure logic
        from amzn_cse_telco_autonomous_network_agents_app.agent.agents.anda.orchestrator import (
            _resolve_nf_order,
        )

        nfs = [
            {"name": "amf", "type": "open5gs-amf"},
            {"name": "nrf", "type": "open5gs-nrf"},
            {"name": "smf", "type": "open5gs-smf"},
            {"name": "gnb", "type": "srsran-gnb"},
            {"name": "upf", "type": "open5gs-upf"},
        ]
        ordered = _resolve_nf_order(nfs)
        names = [nf["name"] for nf in ordered]

        # NRF must come before everything
        assert names.index("nrf") < names.index("amf")
        assert names.index("nrf") < names.index("smf")
        # SMF before UPF (PFCP dependency)
        assert names.index("smf") < names.index("upf")
        # Core before RAN
        assert names.index("amf") < names.index("gnb")

    def test_unknown_nfs_appended_last(self):
        from amzn_cse_telco_autonomous_network_agents_app.agent.agents.anda.orchestrator import (
            _resolve_nf_order,
        )

        nfs = [
            {"name": "custom-app", "type": "custom-app"},
            {"name": "nrf", "type": "open5gs-nrf"},
        ]
        ordered = _resolve_nf_order(nfs)
        names = [nf["name"] for nf in ordered]
        assert names[0] == "nrf"
        assert names[-1] == "custom-app"

    def test_empty_list(self):
        from amzn_cse_telco_autonomous_network_agents_app.agent.agents.anda.orchestrator import (
            _resolve_nf_order,
        )
        assert _resolve_nf_order([]) == []

    def test_single_nf(self):
        from amzn_cse_telco_autonomous_network_agents_app.agent.agents.anda.orchestrator import (
            _resolve_nf_order,
        )
        nfs = [{"name": "amf", "type": "open5gs-amf"}]
        assert _resolve_nf_order(nfs) == nfs
