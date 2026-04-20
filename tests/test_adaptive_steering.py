# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""Tests for AdaptiveSteeringHandler."""
import json
import os
import tempfile
import pytest
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "sop-agent"))

from adaptive_steering import _extract_target, _load_failure_patterns, _build_guidance, AdaptiveSteeringHandler, Guide, Proceed


# ── Target extraction ──

def test_extract_ssh_ip():
    assert _extract_target("ssh_command", "ssh ec2-user@100.77.0.105 'systemctl status'") == "100.77.0.105"

def test_extract_run_command_ssh():
    assert _extract_target("run_command", "ssh -i /root/.ssh/id_rsa 100.77.0.105") == "100.77.0.105"

def test_extract_ssh_hostname():
    assert _extract_target("ssh_command", "ssh ec2-user@bastion.internal 'ls'") == "bastion.internal"

def test_extract_no_target_kubectl():
    assert _extract_target("kubectl", "get pods -n aws-app") is None

def test_extract_ssm():
    assert _extract_target("run_command", "aws ssm start-session --target instance-id i-0abc123") == "i-0abc123"


# ── Pattern loading ──

@pytest.fixture
def log_dir_with_history():
    d = tempfile.mkdtemp()
    log_path = Path(d) / "logs"
    log_path.mkdir()

    # Create 3 runs where SSH to 100.77.0.105 fails
    for i in range(3):
        record = {
            "run_id": f"2026040{i}_120000",
            "nodes": {
                "06-monitoring": {
                    "tool_calls": [
                        {"tool": "kubectl", "input": "get pods -n monitoring", "result": "OK", "error": None},
                        {"tool": "ssh_command", "input": "ssh ec2-user@100.77.0.105 systemctl status", "result": None, "error": "Connection refused"},
                        {"tool": "run_command", "input": "ssh -i /root/.ssh/id_rsa 100.77.0.105", "result": None, "error": "Permission denied"},
                    ]
                }
            }
        }
        (log_path / f"execution_2026040{i}_120000.json").write_text(json.dumps(record))

    yield str(log_path)


def test_load_failure_patterns(log_dir_with_history):
    patterns = _load_failure_patterns("06-monitoring", log_dir_with_history)
    assert len(patterns) >= 1
    targets = [p["target"] for p in patterns]
    assert "100.77.0.105" in targets
    # Should have count >= 2
    for p in patterns:
        if p["target"] == "100.77.0.105":
            assert p["count"] >= 2
            assert "SSH" in p["guidance"] or "ssh" in p["guidance"].lower()


def test_no_patterns_for_clean_sop(log_dir_with_history):
    patterns = _load_failure_patterns("01-argocd-setup", log_dir_with_history)
    assert len(patterns) == 0


def test_no_patterns_without_logs():
    patterns = _load_failure_patterns("06-monitoring", "/nonexistent/path")
    assert len(patterns) == 0


# ── Steering decisions ──

@pytest.mark.asyncio
async def test_guide_on_known_failure(log_dir_with_history):
    handler = AdaptiveSteeringHandler("06-monitoring", log_dir=log_dir_with_history)
    assert len(handler.patterns) >= 1

    action = await handler.steer_before_tool(
        agent=None,
        tool_use={"name": "ssh_command", "input": {"command": "ssh ec2-user@100.77.0.105 systemctl status"}},
    )
    assert isinstance(action, Guide)
    assert "100.77.0.105" in action.reason


@pytest.mark.asyncio
async def test_proceed_on_unknown_target(log_dir_with_history):
    handler = AdaptiveSteeringHandler("06-monitoring", log_dir=log_dir_with_history)

    action = await handler.steer_before_tool(
        agent=None,
        tool_use={"name": "kubectl", "input": {"command": "get pods -n monitoring"}},
    )
    assert isinstance(action, Proceed)


@pytest.mark.asyncio
async def test_guide_only_once_per_target(log_dir_with_history):
    """Don't spam the agent with the same guidance repeatedly."""
    handler = AdaptiveSteeringHandler("06-monitoring", log_dir=log_dir_with_history)

    # First call: Guide
    a1 = await handler.steer_before_tool(
        agent=None,
        tool_use={"name": "ssh_command", "input": {"command": "ssh 100.77.0.105"}},
    )
    assert isinstance(a1, Guide)

    # Second call to same target: Proceed (already guided)
    a2 = await handler.steer_before_tool(
        agent=None,
        tool_use={"name": "run_command", "input": {"command": "ssh 100.77.0.105"}},
    )
    assert isinstance(a2, Proceed)


@pytest.mark.asyncio
async def test_tool_budget_enforcement():
    handler = AdaptiveSteeringHandler("01-argocd-setup", log_dir="/nonexistent")
    handler.tool_budget = 3

    for _ in range(2):
        a = await handler.steer_before_tool(agent=None, tool_use={"name": "kubectl", "input": {}})
        assert isinstance(a, Proceed)

    a = await handler.steer_before_tool(agent=None, tool_use={"name": "kubectl", "input": {}})
    assert isinstance(a, Guide)
    assert "budget" in a.reason.lower()


@pytest.mark.asyncio
async def test_namespace_guard():
    handler = AdaptiveSteeringHandler("01-argocd-setup", log_dir="/nonexistent")

    action = await handler.steer_before_tool(
        agent=None,
        tool_use={"name": "kubectl", "input": {"args": "get pods -n default"}},
    )
    assert isinstance(action, Guide)
    assert "aws-app" in action.reason
