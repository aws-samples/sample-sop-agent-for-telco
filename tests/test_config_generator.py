# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Unit tests for ANDA config generation primitives (ISV-agnostic)."""

import sys
from dataclasses import dataclass
from unittest.mock import MagicMock, patch

sys.modules.setdefault("strands", MagicMock())

from amzn_cse_telco_autonomous_network_agents_app.agent.agents.anda.config_generator import (
    CONFIG_GEN_TOOLS,
    describe_node,
    helm_dry_run,
    kubectl_query,
    read_helm_values,
    save_generated_values,
)


@dataclass
class FakeCmdResult:
    success: bool
    output: str
    stdout: str = ""
    stderr: str = ""
    returncode: int = 0

    def __post_init__(self):
        if not self.stdout:
            self.stdout = self.output


class TestReadHelmValues:
    def test_reads_values_file(self, tmp_path):
        chart = tmp_path / "chart"
        chart.mkdir()
        (chart / "values.yaml").write_text("image:\n  repository: my-registry/upf\n")
        result = read_helm_values(str(chart))
        assert "my-registry/upf" in result

    def test_missing_values_file(self, tmp_path):
        result = read_helm_values(str(tmp_path))
        assert "Error" in result and "not found" in result


class TestDescribeNode:
    @patch("amzn_cse_telco_autonomous_network_agents_app.agent.agents.anda.config_generator.run_cmd")
    def test_describes_named_node(self, mock_run):
        mock_run.return_value = FakeCmdResult(success=True, output='{"metadata":{"name":"worker-001"}}')
        result = describe_node("worker-001")
        assert "worker-001" in result
        assert "kubectl get node worker-001" in mock_run.call_args[0][0]

    @patch("amzn_cse_telco_autonomous_network_agents_app.agent.agents.anda.config_generator.run_cmd")
    def test_picks_first_node_when_empty(self, mock_run):
        mock_run.side_effect = [
            FakeCmdResult(success=True, output="worker-001\nworker-002"),
            FakeCmdResult(success=True, output='{"metadata":{"name":"worker-001"}}'),
        ]
        result = describe_node()
        assert "worker-001" in result


class TestKubectlQuery:
    @patch("amzn_cse_telco_autonomous_network_agents_app.agent.agents.anda.config_generator.run_cmd")
    def test_allows_read_verbs(self, mock_run):
        mock_run.return_value = FakeCmdResult(success=True, output='{"items":[]}')
        result = kubectl_query("get net-attach-def -A -o json")
        assert "items" in result

    def test_blocks_write_verbs(self):
        result = kubectl_query("delete pod foo")
        assert "Error" in result and "read-only" in result

    def test_blocks_apply(self):
        result = kubectl_query("apply -f manifest.yaml")
        assert "Error" in result


class TestHelmDryRun:
    @patch("amzn_cse_telco_autonomous_network_agents_app.agent.agents.anda.config_generator.run_cmd")
    def test_pass_on_valid_render(self, mock_run, tmp_path):
        chart = tmp_path / "chart"
        chart.mkdir()
        mock_run.return_value = FakeCmdResult(success=True, output="kind: Deployment\nkind: Service")
        result = helm_dry_run(str(chart), "image:\n  tag: latest")
        assert "PASS" in result
        assert "2 resources" in result

    @patch("amzn_cse_telco_autonomous_network_agents_app.agent.agents.anda.config_generator.run_cmd")
    def test_fail_on_render_error(self, mock_run, tmp_path):
        chart = tmp_path / "chart"
        chart.mkdir()
        mock_run.return_value = FakeCmdResult(success=False, output="Error: template parse failed")
        result = helm_dry_run(str(chart), "bad: yaml")
        assert "FAIL" in result

    def test_missing_chart(self, tmp_path):
        result = helm_dry_run(str(tmp_path / "nonexistent"), "x: y")
        assert "Error" in result and "not found" in result


class TestSaveGeneratedValues:
    def test_saves_to_output_dir(self, tmp_path, monkeypatch):
        monkeypatch.setenv("GENERATED_CONFIG_DIR", str(tmp_path))
        result = save_generated_values("image:\n  tag: v1", "test-values.yaml")
        assert "Saved" in result
        assert (tmp_path / "test-values.yaml").read_text() == "image:\n  tag: v1"


class TestToolRegistration:
    def test_all_tools_registered(self):
        assert len(CONFIG_GEN_TOOLS) == 5
        names = {t.__name__ for t in CONFIG_GEN_TOOLS}
        assert names == {"read_helm_values", "describe_node", "kubectl_query", "helm_dry_run", "save_generated_values"}
