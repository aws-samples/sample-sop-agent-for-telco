# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Tests for sop_executor.py — tools, parsing, command execution."""
import subprocess
from unittest.mock import MagicMock, patch

from amzn_cse_telco_autonomous_network_agents_app.agent.sop_executor import (
    _MODEL_TIER_MAP,
    ARGOCD_TOOLS,
    BASE_TOOLS,
    CmdResult,
    get_tools_for_sop,
    parse_sop,
    run_cmd,
)

# ── CmdResult ──

class TestCmdResult:
    def test_success_property(self):
        r = CmdResult("out", "", 0)
        assert r.success is True

    def test_failure_property(self):
        r = CmdResult("", "err", 1)
        assert r.success is False

    def test_output_includes_stderr(self):
        r = CmdResult("out", "err", 0)
        assert "STDERR: err" in r.output

    def test_output_includes_exit_code_on_failure(self):
        r = CmdResult("out", "", 2)
        assert "EXIT_CODE: 2" in r.output

    def test_output_empty(self):
        r = CmdResult("", "", 0)
        assert r.output == "No output"


# ── run_cmd ──

class TestRunCmd:
    @patch("amzn_cse_telco_autonomous_network_agents_app.agent.core.executor.subprocess.run")
    def test_success(self, mock_run):
        mock_run.return_value = MagicMock(stdout="ok", stderr="", returncode=0)
        result = run_cmd("echo hello")
        assert result.success
        assert result.stdout == "ok"

    @patch("amzn_cse_telco_autonomous_network_agents_app.agent.core.executor.subprocess.run")
    def test_failure(self, mock_run):
        mock_run.return_value = MagicMock(stdout="", stderr="bad", returncode=1)
        result = run_cmd("false")
        assert not result.success
        assert result.returncode == 1

    @patch("amzn_cse_telco_autonomous_network_agents_app.agent.core.executor.subprocess.run", side_effect=subprocess.TimeoutExpired("cmd", 5))
    def test_timeout(self, mock_run):
        result = run_cmd("sleep 999", timeout=1)
        assert result.returncode == -1
        assert "timed out" in result.stderr.lower()

    @patch("amzn_cse_telco_autonomous_network_agents_app.agent.core.executor.subprocess.run", side_effect=OSError("no such file"))
    def test_exception(self, mock_run):
        result = run_cmd("nonexistent")
        assert result.returncode == -1


# ── parse_sop ──

class TestParseSop:
    SAMPLE_SOP = """# Test SOP

## Prerequisites
- App deployed
- BGP neighbors up

## Procedure

### Step 1
```bash
kubectl get pods -n aws-app
```

### Step 2
```bash
kubectl exec -n aws-app $POD -- echo test
```

## Success Criteria
- All pods Running
- Zero packet loss

## Troubleshooting

| Issue | Fix |
|-------|-----|
| Pod crash | Restart pod |
"""

    def test_extracts_steps(self):
        result = parse_sop(self.SAMPLE_SOP)
        assert "kubectl get pods" in result
        assert "kubectl exec" in result

    def test_extracts_prerequisites(self):
        result = parse_sop(self.SAMPLE_SOP)
        assert "App deployed" in result

    def test_extracts_success_criteria(self):
        result = parse_sop(self.SAMPLE_SOP)
        assert "All pods Running" in result

    def test_extracts_troubleshooting(self):
        result = parse_sop(self.SAMPLE_SOP)
        assert "Pod crash" in result

    def test_empty_sop(self):
        result = parse_sop("# Empty SOP\n\nNo sections here.")
        assert "0 steps" in result or "steps" in result


# ── get_tools_for_sop ──

class TestGetToolsForSop:
    def test_argocd_sop_gets_argocd_tools(self):
        tools = get_tools_for_sop("sops/07-argocd-monitoring.md")
        assert len(tools) > len(BASE_TOOLS)

    def test_regular_sop_gets_base_tools(self):
        tools = get_tools_for_sop("sops/03-validation.md")
        assert tools == BASE_TOOLS

    def test_unknown_sop_gets_base_tools(self):
        tools = get_tools_for_sop("sops/99-unknown.md")
        assert tools == BASE_TOOLS


# ── Tool function contracts ──

class TestToolContracts:
    """Verify tools are callable and have proper signatures."""

    def test_base_tools_count(self):
        assert len(BASE_TOOLS) == 16

    def test_all_tools_callable(self):
        for t in BASE_TOOLS:
            assert callable(t)

    def test_argocd_tools_count(self):
        assert len(ARGOCD_TOOLS) == 2

    def test_model_tier_map(self):
        assert "haiku" in _MODEL_TIER_MAP
        assert "sonnet" in _MODEL_TIER_MAP
        assert "opus" in _MODEL_TIER_MAP


# ── Modularity guardrail (S2.2) ──

class TestSingleSourceOfTruth:
    """Guardrail: sop_executor must REUSE core.executor's primitives, not re-fork them.

    These assert object identity (`is`), so if anyone re-defines run_cmd / kubectl /
    BASE_TOOLS inside sop_executor again, this fails loudly. Keeps the executor a
    single source of truth (the whole point of S2.2).
    """

    def test_primitives_are_core_objects(self):
        from amzn_cse_telco_autonomous_network_agents_app.agent import (
            sop_executor as se,
        )
        from amzn_cse_telco_autonomous_network_agents_app.agent.core import (
            executor as core,
        )

        assert se.run_cmd is core.run_cmd
        assert se.kubectl is core.kubectl
        assert se.ssm_command is core.ssm_command
        assert se.redfish_query is core.redfish_query

    def test_tool_lists_are_core_objects(self):
        from amzn_cse_telco_autonomous_network_agents_app.agent import (
            sop_executor as se,
        )
        from amzn_cse_telco_autonomous_network_agents_app.agent.core import (
            executor as core,
        )

        assert se.BASE_TOOLS is core.BASE_TOOLS
        assert se.get_tools_for_sop is core.get_tools_for_sop

    def test_argocd_selection_returns_core_tool_set(self):
        # Ties "symbols are shared" to "selection logic returns the core tools" —
        # asserts the exact set, not just len > base.
        from amzn_cse_telco_autonomous_network_agents_app.agent import (
            sop_executor as se,
        )
        from amzn_cse_telco_autonomous_network_agents_app.agent.core import (
            executor as core,
        )

        assert se.get_tools_for_sop("sops/07-argocd-monitoring.md") == core.BASE_TOOLS + core.ARGOCD_TOOLS


# ── Tool input safety ──

class TestToolInputSafety:
    """Verify tools handle edge cases."""

    @patch("amzn_cse_telco_autonomous_network_agents_app.agent.core.executor.run_cmd")
    def test_kubectl_passes_args(self, mock_run):
        from amzn_cse_telco_autonomous_network_agents_app.agent.sop_executor import (
            kubectl,
        )
        mock_run.return_value = CmdResult("ok", "", 0)
        kubectl("get pods -n aws-app")
        mock_run.assert_called_once()
        call_args = mock_run.call_args[0][0]
        assert "kubectl get pods -n aws-app" in call_args

    @patch("amzn_cse_telco_autonomous_network_agents_app.agent.core.executor.run_cmd")
    def test_ssh_command_constructs_properly(self, mock_run):
        from amzn_cse_telco_autonomous_network_agents_app.agent.sop_executor import (
            ssh_command,
        )
        mock_run.return_value = CmdResult("ok", "", 0)
        ssh_command("10.10.4.238", "ls /tmp", user="nec")
        call_args = mock_run.call_args[0][0]
        assert "nec@10.10.4.238" in call_args
        assert "ls /tmp" in call_args

    @patch("amzn_cse_telco_autonomous_network_agents_app.agent.core.executor.run_cmd")
    def test_telcocli_includes_profile(self, mock_run):
        from amzn_cse_telco_autonomous_network_agents_app.agent.sop_executor import (
            telcocli,
        )
        mock_run.return_value = CmdResult("ok", "", 0)
        telcocli("list-outposts")
        call_args = mock_run.call_args[0][0]
        assert "--profile nec" in call_args
        assert "--region us-east-1" in call_args
