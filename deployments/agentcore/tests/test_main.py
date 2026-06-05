# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Tests for the AgentCore entry point.

These tests exercise the routing and SOP path resolution without making
real Bedrock or kubectl calls. The agent itself is mocked.
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Make `main` importable when running pytest from this directory or repo root
_here = Path(__file__).resolve().parent
sys.path.insert(0, str(_here.parent))


@pytest.fixture(autouse=True)
def _isolate_agent_cache():
    """Reset the cached agent dict between tests so mocks don't leak."""
    import main as _main

    _main._agent_cache.clear()
    yield
    _main._agent_cache.clear()


@pytest.fixture
def mock_agent():
    """Mock the Strands agent factory so we don't hit Bedrock."""
    with patch("main.create_agent") as create:
        agent = MagicMock()
        agent.return_value = "mocked agent response"
        create.return_value = (agent, {})
        yield agent


def test_unknown_action_returns_error():
    import main

    result = main.invoke({"action": "fly_to_moon"})

    assert "error" in result
    assert "supported_actions" in result


def test_missing_prompt_returns_error(mock_agent):
    import main

    result = main.invoke({"prompt": ""})

    assert "error" in result


def test_free_form_prompt_routes_to_agent(mock_agent):
    import main

    result = main.invoke({"prompt": "What is the cluster health?"})

    assert result["result"] == "mocked agent response"
    assert "model" in result
    mock_agent.assert_called_once()


def test_run_sop_missing_field_returns_error(mock_agent):
    import main

    result = main.invoke({"action": "run_sop"})

    assert "error" in result
    assert "sop" in result["error"]


def test_run_sop_not_found_returns_error(mock_agent):
    import main

    result = main.invoke({"action": "run_sop", "sop": "nonexistent-sop-xyz"})

    assert "error" in result
    assert "not found" in result["error"].lower()


def test_run_sop_resolves_workshop_sop(mock_agent, tmp_path, monkeypatch):
    import main

    # Create a fake SOP repo
    sops_dir = tmp_path / "sops" / "workshop-deploy"
    sops_dir.mkdir(parents=True)
    sop_file = sops_dir / "deploy-test.md"
    sop_file.write_text("# Test SOP\n\nStep 1: do nothing")
    monkeypatch.setenv("SOP_REPO", str(tmp_path))

    result = main.invoke({"action": "run_sop", "sop": "deploy-test"})

    assert "error" not in result
    assert result["sop"] == "deploy-test"
    assert "deploy-test.md" in result["sop_path"]


def test_process_alarms_empty_list(mock_agent):
    import main

    result = main.invoke({"action": "process_alarms", "alarms": []})

    assert result["alarms_processed"] == 0


def test_process_alarms_with_alarm(mock_agent):
    import main

    result = main.invoke(
        {
            "action": "process_alarms",
            "alarms": [{"name": "nf-crashloop", "severity": "high"}],
        }
    )

    assert result["alarms_processed"] == 1
    assert "summary" in result
    mock_agent.assert_called_once()


def test_agent_cache_reuses_instance(mock_agent):
    """Same (sop, model, fix_mode) tuple should reuse the cached agent."""
    import main

    main.invoke({"prompt": "first"})
    main.invoke({"prompt": "second"})

    # `create_agent` should be called once even though `invoke` ran twice
    # (the mocked agent itself is called twice, but the factory only once).
    from main import create_agent as factory  # noqa: F401

    # Look at the patched factory
    main_module = sys.modules["main"]
    assert main_module.create_agent.call_count == 1
