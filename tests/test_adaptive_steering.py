# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Tests for adaptive_steering.py — failure pattern learning and steering decisions."""
import json

import pytest

from amzn_cse_telco_autonomous_network_agents_app.agent.adaptive_steering import (
    AdaptiveSteeringHandler,
    _build_guidance,
    _extract_target,
    _load_failure_patterns,
)


class TestExtractTarget:
    def test_ssh_ip(self):
        assert _extract_target("ssh_command", "ssh root@192.168.1.1 uptime") == "192.168.1.1"

    def test_ssh_at_hostname(self):
        assert _extract_target("ssh_command", "ssh user@myhost.local") == "myhost.local"

    def test_run_command_with_ssh(self):
        assert _extract_target("run_command", "ssh 10.0.0.5 ls") == "10.0.0.5"

    def test_ssm_instance_id(self):
        assert _extract_target("run_command", "aws ssm send-command --instance-id i-0abc123def") == "i-0abc123def"

    def test_no_target_kubectl(self):
        assert _extract_target("kubectl", "get pods -n srsran") is None

    def test_no_target_empty(self):
        assert _extract_target("run_command", "ls -la") is None


class TestBuildGuidance:
    def test_ssh_guidance(self):
        g = _build_guidance("ssh_command", "192.168.1.1", {"connection refused"})
        assert "SSH" in g
        assert "192.168.1.1" in g
        assert "kubectl" in g.lower() or "Kubernetes" in g

    def test_ssm_guidance(self):
        g = _build_guidance("ssm_command", "i-abc", {"ssm timeout"})
        assert "SSM" in g

    def test_generic_guidance(self):
        g = _build_guidance("custom_tool", "target", {"some error"})
        assert "custom_tool" in g
        assert "target" in g


class TestLoadFailurePatterns:
    def test_empty_dir(self, tmp_path):
        patterns = _load_failure_patterns("test_sop", str(tmp_path))
        assert patterns == []

    def test_loads_repeated_failures(self, tmp_path):
        for i in range(3):
            log_file = tmp_path / f"execution_{i}.json"
            log_file.write_text(json.dumps({
                "nodes": {"test_sop": {"tool_calls": [
                    {"tool": "ssh_command", "input": "ssh root@10.0.0.1 uptime", "error": "connection refused"}
                ]}}
            }))
        patterns = _load_failure_patterns("test_sop", str(tmp_path))
        assert len(patterns) == 1
        assert patterns[0]["target"] == "10.0.0.1"
        assert patterns[0]["count"] >= 2

    def test_single_failure_not_pattern(self, tmp_path):
        log_file = tmp_path / "execution_0.json"
        log_file.write_text(json.dumps({
            "nodes": {"test_sop": {"tool_calls": [
                {"tool": "ssh_command", "input": "ssh root@10.0.0.1 uptime", "error": "timeout"}
            ]}}
        }))
        patterns = _load_failure_patterns("test_sop", str(tmp_path))
        assert patterns == []

    def test_no_error_not_counted(self, tmp_path):
        for i in range(3):
            log_file = tmp_path / f"execution_{i}.json"
            log_file.write_text(json.dumps({
                "nodes": {"test_sop": {"tool_calls": [
                    {"tool": "ssh_command", "input": "ssh root@10.0.0.1 uptime", "error": ""}
                ]}}
            }))
        patterns = _load_failure_patterns("test_sop", str(tmp_path))
        assert patterns == []


class TestAdaptiveSteeringHandler:
    @pytest.fixture
    def handler(self, tmp_path):
        return AdaptiveSteeringHandler("test_sop", fix_mode=True, log_dir=str(tmp_path))

    @pytest.mark.asyncio
    async def test_proceed_normal_tool(self, handler):
        tool_use = {"name": "kubectl", "input": {"args": "get pods -n srsran"}}
        result = await handler.steer_before_tool(agent=None, tool_use=tool_use)
        assert result.__class__.__name__ == "Proceed"

    @pytest.mark.asyncio
    async def test_budget_exhausted(self, handler):
        handler.tool_count = 95
        tool_use = {"name": "kubectl", "input": {}}
        result = await handler.steer_before_tool(agent=None, tool_use=tool_use)
        assert result.__class__.__name__ == "Guide"
        assert "budget" in result.reason.lower()

    @pytest.mark.asyncio
    async def test_blocks_known_failure(self, tmp_path):
        # Create failure history
        for i in range(3):
            (tmp_path / f"execution_{i}.json").write_text(json.dumps({
                "nodes": {"my_sop": {"tool_calls": [
                    {"tool": "ssh_command", "input": "ssh root@10.0.0.5 check", "error": "connection refused"}
                ]}}
            }))
        handler = AdaptiveSteeringHandler("my_sop", fix_mode=True, log_dir=str(tmp_path))
        tool_use = {"name": "ssh_command", "input": {"command": "ssh root@10.0.0.5 uptime"}}
        result = await handler.steer_before_tool(agent=None, tool_use=tool_use)
        assert result.__class__.__name__ == "Guide"
        assert "10.0.0.5" in result.reason

    @pytest.mark.asyncio
    async def test_port_forward_without_background(self, handler):
        tool_use = {"name": "run_command", "input": {"command": "kubectl port-forward svc/x 8080:80"}}
        result = await handler.steer_before_tool(agent=None, tool_use=tool_use)
        assert result.__class__.__name__ == "Guide"
        assert "port-forward" in result.reason

    @pytest.mark.asyncio
    async def test_port_forward_with_background_ok(self, handler):
        tool_use = {"name": "run_command", "input": {"command": "kubectl port-forward svc/x 8080:80 &"}}
        result = await handler.steer_before_tool(agent=None, tool_use=tool_use)
        assert result.__class__.__name__ == "Proceed"

    @pytest.mark.asyncio
    async def test_report_mode_blocks_destructive(self, tmp_path):
        handler = AdaptiveSteeringHandler("test", fix_mode=False, log_dir=str(tmp_path))
        tool_use = {"name": "run_command", "input": {"command": "sudo reboot"}}
        result = await handler.steer_before_tool(agent=None, tool_use=tool_use)
        assert result.__class__.__name__ == "Guide"
        assert "REPORT mode" in result.reason

    @pytest.mark.asyncio
    async def test_fix_mode_allows_destructive(self, handler):
        handler.fix_mode = True
        tool_use = {"name": "run_command", "input": {"command": "sudo reboot"}}
        result = await handler.steer_before_tool(agent=None, tool_use=tool_use)
        assert result.__class__.__name__ == "Proceed"
