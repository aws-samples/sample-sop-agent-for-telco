"""ssm_command must pass the remote command to the AWS CLI unchanged.

Regression test for the gtp5g check in deploy-free5gc-core: a command with
inner double quotes and $? broke the hand-built --parameters string
("Error parsing parameter '--parameters'"). No AWS calls are made: run_cmd
is replaced with a fake that records the command lines.
"""

import json
import shlex
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from amzn_cse_telco_autonomous_network_agents_app.agent.core import executor

GTP5G_CHECK = 'lsmod | grep gtp5g; echo "lsmod_exit=$?"; modinfo gtp5g 2>/dev/null | grep -E ^version'


def _run(monkeypatch: pytest.MonkeyPatch, command: str, env: dict) -> list:
    for name in ("AWS_REGION", "AWS_DEFAULT_REGION"):
        monkeypatch.delenv(name, raising=False)
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    calls = []

    def _fake_run_cmd(cmd, timeout=0, shell=True):
        calls.append(cmd)
        if "send-command" in cmd:
            return executor.CmdResult("cmd-123\n", "", 0)
        return executor.CmdResult("Success\tok\t", "", 0)

    fake_site = SimpleNamespace(cluster_region="us-west-1", bedrock_profile="")
    with patch.object(executor, "_get_site_config", return_value=fake_site), patch.object(executor, "run_cmd", side_effect=_fake_run_cmd), patch("time.sleep"):
        executor.ssm_command("i-0123456789abcdef0", command, timeout=3)
    return calls


def _arg(argv: list, flag: str) -> str:
    return argv[argv.index(flag) + 1]


def test_ssm_command_preserves_quotes_and_shell_syntax(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _run(monkeypatch, GTP5G_CHECK, {"AWS_DEFAULT_REGION": "us-east-1"})
    argv = shlex.split(calls[0])
    assert json.loads(_arg(argv, "--parameters")) == {"commands": [GTP5G_CHECK]}


def test_ssm_command_uses_runtime_region_over_site_default(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _run(monkeypatch, "uptime", {"AWS_DEFAULT_REGION": "us-east-1"})
    assert all(_arg(shlex.split(c), "--region") == "us-east-1" for c in calls)

    calls = _run(monkeypatch, "uptime", {"AWS_REGION": "us-west-2", "AWS_DEFAULT_REGION": "us-east-1"})
    assert _arg(shlex.split(calls[0]), "--region") == "us-west-2"


def test_ssm_command_falls_back_to_site_config_region(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _run(monkeypatch, "uptime", {})
    assert _arg(shlex.split(calls[0]), "--region") == "us-west-1"
