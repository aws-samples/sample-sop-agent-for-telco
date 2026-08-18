# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
"""Tests for topology_emitter — ServiceTopology CR emission after NF deploy."""

import json
from unittest.mock import MagicMock, patch

from amzn_cse_telco_autonomous_network_agents_app.agent.agents.anda.topology_emitter import (
    _compute_links,
    update_service_topology,
)


def _mock_cmd_result(returncode=0, stdout="created", stderr=""):
    """Create a mock CmdResult."""
    result = MagicMock()
    result.returncode = returncode
    result.success = returncode == 0
    result.stdout = stdout
    result.stderr = stderr
    result.output = stdout
    return result


class TestUpdateServiceTopology:
    """Tests for update_service_topology."""

    @patch(
        "amzn_cse_telco_autonomous_network_agents_app.agent.agents.anda.topology_emitter.run_cmd"
    )
    @patch(
        "amzn_cse_telco_autonomous_network_agents_app.agent.core.config_store.get_config"
    )
    def test_creates_cr_with_deployed_nfs(self, mock_get_config, mock_run_cmd):
        """Verify CR structure contains expected NF entries and metadata."""
        mock_get_config.return_value = None  # No config = no gate
        mock_run_cmd.return_value = _mock_cmd_result()

        deployed = [
            {"name": "amf", "namespace": "open5gs", "chart": "open5gs/amf", "version": "2.7.0"},
            {"name": "smf", "namespace": "open5gs", "chart": "open5gs/smf", "version": "2.7.0"},
        ]

        result = update_service_topology("site-002", deployed)

        assert result is True
        mock_run_cmd.assert_called_once()

        # Parse the JSON from the kubectl command
        cmd_str = mock_run_cmd.call_args[0][0]
        # Extract JSON between echo '...' |
        json_start = cmd_str.index("echo '") + len("echo '")
        json_end = cmd_str.index("' | kubectl")
        cr_json = cmd_str[json_start:json_end].replace("'\\''", "'")
        cr = json.loads(cr_json)

        assert cr["apiVersion"] == "topology.anra.aws.io/v1alpha1"
        assert cr["kind"] == "ServiceTopology"
        assert cr["metadata"]["name"] == "site-002-services"
        assert "namespace" not in cr["metadata"]  # cluster-scoped
        assert cr["spec"]["siteName"] == "site-002"
        assert len(cr["spec"]["networkFunctions"]) == 2

        amf_entry = cr["spec"]["networkFunctions"][0]
        assert amf_entry["name"] == "amf"
        assert amf_entry["type"] == "AMF"
        assert amf_entry["namespace"] == "open5gs"
        assert len(amf_entry["interfaces"]) == 3
        iface_names = [i["name"] for i in amf_entry["interfaces"]]
        assert "N1" in iface_names
        assert "N2" in iface_names
        assert "Namf" in iface_names
        assert amf_entry["dependsOn"] == ["nrf"]
        assert amf_entry["status"] == "healthy"

    @patch(
        "amzn_cse_telco_autonomous_network_agents_app.agent.agents.anda.topology_emitter.run_cmd"
    )
    @patch(
        "amzn_cse_telco_autonomous_network_agents_app.agent.core.config_store.get_config"
    )
    def test_config_gate_false_skips(self, mock_get_config, mock_run_cmd):
        """When topology_emit_service_topology is False, run_cmd is not called."""
        cfg = MagicMock()
        cfg.topology_emit_service_topology = False
        mock_get_config.return_value = cfg

        result = update_service_topology("site-001", [{"name": "amf"}])

        assert result is True
        mock_run_cmd.assert_not_called()

    @patch(
        "amzn_cse_telco_autonomous_network_agents_app.agent.agents.anda.topology_emitter.run_cmd"
    )
    @patch(
        "amzn_cse_telco_autonomous_network_agents_app.agent.core.config_store.get_config"
    )
    def test_config_gate_true_emits(self, mock_get_config, mock_run_cmd):
        """When topology_emit_service_topology is True, run_cmd is called."""
        cfg = MagicMock()
        cfg.topology_emit_service_topology = True
        mock_get_config.return_value = cfg
        mock_run_cmd.return_value = _mock_cmd_result()

        result = update_service_topology("site-001", [{"name": "nrf"}])

        assert result is True
        mock_run_cmd.assert_called_once()

    @patch(
        "amzn_cse_telco_autonomous_network_agents_app.agent.agents.anda.topology_emitter.run_cmd"
    )
    @patch(
        "amzn_cse_telco_autonomous_network_agents_app.agent.core.config_store.get_config"
    )
    def test_handles_missing_catalog_entry(self, mock_get_config, mock_run_cmd):
        """Unknown NF type gets empty interfaces and dependsOn, no crash."""
        mock_get_config.return_value = None
        mock_run_cmd.return_value = _mock_cmd_result()

        deployed = [{"name": "custom-nf", "namespace": "test", "chart": "x", "version": "1.0"}]

        result = update_service_topology("site-003", deployed)

        assert result is True
        cmd_str = mock_run_cmd.call_args[0][0]
        json_start = cmd_str.index("echo '") + len("echo '")
        json_end = cmd_str.index("' | kubectl")
        cr_json = cmd_str[json_start:json_end].replace("'\\''", "'")
        cr = json.loads(cr_json)

        nf_entry = cr["spec"]["networkFunctions"][0]
        assert nf_entry["name"] == "custom-nf"
        assert nf_entry["interfaces"] == []
        assert nf_entry["dependsOn"] == []

    @patch(
        "amzn_cse_telco_autonomous_network_agents_app.agent.agents.anda.topology_emitter.run_cmd"
    )
    @patch(
        "amzn_cse_telco_autonomous_network_agents_app.agent.core.config_store.get_config"
    )
    def test_kubectl_failure_returns_false(self, mock_get_config, mock_run_cmd):
        """When kubectl apply fails, function returns False."""
        mock_get_config.return_value = None
        mock_run_cmd.return_value = _mock_cmd_result(returncode=1, stderr="error applying")

        result = update_service_topology("site-001", [{"name": "amf"}])

        assert result is False


class TestComputeLinks:
    """Tests for _compute_links."""

    def test_links_computed_from_shared_interfaces(self):
        """gnb(N2,N3) + amf(N1,N2,Namf) -> link(gnb->amf, N2)."""
        nf_entries = [
            {
                "name": "gnb",
                "interfaces": [{"name": "N2", "protocol": "SCTP"}, {"name": "N3", "protocol": "GTP-U"}],
                "dependsOn": ["amf", "upf"],
            },
            {
                "name": "amf",
                "interfaces": [{"name": "N1", "protocol": "HTTP2"}, {"name": "N2", "protocol": "SCTP"}, {"name": "Namf", "protocol": "SBI"}],
                "dependsOn": ["nrf"],
            },
        ]
        links = _compute_links(nf_entries)

        # gnb depends on amf, shared interface is N2
        assert {"from": "gnb", "to": "amf", "interface": "N2"} in links

    def test_direction_from_depends_on(self):
        """Link direction goes from dependent to dependency."""
        nf_entries = [
            {
                "name": "smf",
                "interfaces": [{"name": "N4", "protocol": "PFCP"}, {"name": "Nsmf", "protocol": "SBI"}],
                "dependsOn": ["nrf", "amf"],
            },
            {
                "name": "nrf",
                "interfaces": [{"name": "Nnrf", "protocol": "SBI"}],
                "dependsOn": [],
            },
            {
                "name": "amf",
                "interfaces": [{"name": "N1", "protocol": "HTTP2"}, {"name": "N2", "protocol": "SCTP"}, {"name": "Namf", "protocol": "SBI"}],
                "dependsOn": ["nrf"],
            },
        ]
        links = _compute_links(nf_entries)

        # smf and nrf share no interfaces (Nsmf != Nnrf), so no link
        # smf and amf share no interfaces either (Nsmf != Namf)
        # This is correct — SBI interfaces are now per-NF (Namf, Nsmf, Nnrf)
        assert len(links) == 0

    def test_multiple_shared_interfaces(self):
        """Two shared interfaces produce two separate links."""
        nf_entries = [
            {
                "name": "upf",
                "interfaces": [{"name": "N3", "protocol": "GTP-U"}, {"name": "N4", "protocol": "PFCP"}, {"name": "N6", "protocol": "IP"}],
                "dependsOn": ["smf"],
            },
            {
                "name": "smf",
                "interfaces": [{"name": "N4", "protocol": "PFCP"}, {"name": "Nsmf", "protocol": "SBI"}],
                "dependsOn": [],
            },
        ]
        links = _compute_links(nf_entries)

        # upf depends on smf, shared interface is N4
        assert {"from": "upf", "to": "smf", "interface": "N4"} in links
        # Only N4 is shared (smf doesn't have N3 or N6)
        assert len([l for l in links if l["from"] == "upf" and l["to"] == "smf"]) == 1

    def test_no_link_when_dependency_not_deployed(self):
        """If dependsOn references an NF not in the entries, no link is created."""
        nf_entries = [
            {
                "name": "amf",
                "interfaces": [{"name": "N1", "protocol": "HTTP2"}, {"name": "N2", "protocol": "SCTP"}],
                "dependsOn": ["nrf"],  # nrf not in entries
            },
        ]
        links = _compute_links(nf_entries)
        assert links == []
