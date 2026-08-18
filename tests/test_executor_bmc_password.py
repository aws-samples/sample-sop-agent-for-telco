"""Regression tests for the BMC password env-driven fix.

Both `agent/core/executor.py:redfish_query` and `agent/sop_executor.py:redfish_query`
previously hardcoded the Dell iDRAC default ``calvin`` password. After the fix
they read ``BMC_PASSWORD`` from the environment and return a clear error if
unset, matching the convention already used by monitor.py / discovery.py /
bios_inspector.py / anra/monitoring/hardware_event_log.py.
"""

from types import SimpleNamespace
from unittest.mock import patch

import pytest


def _fake_node(username: str = "root") -> SimpleNamespace:
    """Minimal Node stand-in with the .bmc shape redfish_query reads."""
    return SimpleNamespace(
        bmc=SimpleNamespace(
            username=username,
            thermal_path="/redfish/v1/Chassis/x/Thermal",
            power_path="/redfish/v1/Chassis/x/Power",
            redfish_base="/redfish/v1",
        ),
    )


# ── agent.core.executor.redfish_query ──


def test_executor_redfish_query_uses_env_password(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BMC_PASSWORD", "real-password")
    from amzn_cse_telco_autonomous_network_agents_app.agent.core import executor

    fake_site = SimpleNamespace(
        get_node_by_bmc=lambda _ip: _fake_node(),
        all_bmc_ips=["10.0.0.1"],
    )
    captured: dict = {}

    class _FakeCompleted:
        returncode = 0
        stdout = '{"ok": true}'
        stderr = ""

    def _fake_curl(url, username, password, **_kw) -> _FakeCompleted:
        captured["url"] = url
        captured["username"] = username
        captured["password"] = password
        return _FakeCompleted()

    with patch.object(executor, "_get_site_config", return_value=fake_site), patch("amzn_cse_telco_autonomous_network_agents_app.agent.util.bmc.curl_bmc", side_effect=_fake_curl):
        executor.redfish_query("10.0.0.1", "/Thermal")

    # Password is handed to the hardened helper as an arg (it goes on stdin from
    # there), never composed into a command string at the call site.
    assert captured["password"] == "real-password"
    assert captured["url"].startswith("https://10.0.0.1")


def test_executor_redfish_query_errors_when_password_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("BMC_PASSWORD", raising=False)
    from amzn_cse_telco_autonomous_network_agents_app.agent.core import executor

    fake_site = SimpleNamespace(
        get_node_by_bmc=lambda _ip: _fake_node(),
        all_bmc_ips=["10.0.0.1"],
    )

    def _should_not_be_called(*_a, **_kw):
        raise AssertionError("run_cmd must not be invoked when BMC_PASSWORD is unset")

    with patch.object(executor, "_get_site_config", return_value=fake_site), patch.object(executor, "run_cmd", side_effect=_should_not_be_called):
        result = executor.redfish_query("10.0.0.1", "/Thermal")

    assert "BMC_PASSWORD" in result
    assert "Error" in result


# ── agent.sop_executor.redfish_query ──


# NOTE: sop_executor.redfish_query is now the SAME object as core.executor.redfish_query
# (unified in S2.2). These tests verify the re-exported tool still enforces the
# BMC_PASSWORD contract; they patch core.executor (where the function body lives).
def test_sop_executor_redfish_query_uses_env_password(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BMC_PASSWORD", "another-password")
    from amzn_cse_telco_autonomous_network_agents_app.agent import sop_executor
    from amzn_cse_telco_autonomous_network_agents_app.agent.core import (
        executor as core_executor,
    )

    fake_site = SimpleNamespace(
        get_node_by_bmc=lambda _ip: _fake_node(),
        all_bmc_ips=["10.0.0.2"],
    )
    captured: dict = {}

    class _FakeCompleted:
        returncode = 0
        stdout = '{"ok": true}'
        stderr = ""

    def _fake_curl(url, username, password, **_kw) -> _FakeCompleted:
        captured["password"] = password
        return _FakeCompleted()

    with patch.object(core_executor, "_get_site_config", lambda: fake_site), patch("amzn_cse_telco_autonomous_network_agents_app.agent.util.bmc.curl_bmc", side_effect=_fake_curl):
        sop_executor.redfish_query("10.0.0.2", "/Power")

    assert captured["password"] == "another-password"


def test_sop_executor_redfish_query_errors_when_password_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("BMC_PASSWORD", raising=False)
    from amzn_cse_telco_autonomous_network_agents_app.agent import sop_executor
    from amzn_cse_telco_autonomous_network_agents_app.agent.core import (
        executor as core_executor,
    )

    fake_site = SimpleNamespace(
        get_node_by_bmc=lambda _ip: _fake_node(),
        all_bmc_ips=["10.0.0.2"],
    )

    def _should_not_be_called(*_a, **_kw):
        raise AssertionError("run_cmd must not be invoked when BMC_PASSWORD is unset")

    with patch.object(core_executor, "_get_site_config", lambda: fake_site), patch.object(core_executor, "run_cmd", side_effect=_should_not_be_called):
        result = sop_executor.redfish_query("10.0.0.2", "/Power")

    assert "BMC_PASSWORD" in result
    assert "Error" in result


# ── agent.redfish_events.subscribe_bmc ──


def _fake_bmc_node() -> SimpleNamespace:
    """Stand-in node with the .bmc shape subscribe_bmc reads."""
    return SimpleNamespace(
        name="server-001",
        bmc=SimpleNamespace(username="root", ip="10.0.0.99"),
    )


def test_subscribe_bmc_uses_env_password(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BMC_PASSWORD", "third-password")
    from amzn_cse_telco_autonomous_network_agents_app.agent import redfish_events

    captured: dict = {}

    class _FakeCompleted:
        returncode = 0
        stdout = ""

    def _fake_curl(url, username, password, **_kw) -> _FakeCompleted:
        captured["url"] = url
        captured["password"] = password
        captured["extra_args"] = _kw.get("extra_args", [])
        return _FakeCompleted()

    with patch("amzn_cse_telco_autonomous_network_agents_app.agent.util.bmc.curl_bmc", side_effect=_fake_curl):
        redfish_events.subscribe_bmc(_fake_bmc_node(), "https://anra/webhook")

    # Password goes to the helper (then onto curl's stdin), not onto argv.
    assert captured["password"] == "third-password"
    assert "-u" not in captured["extra_args"]


def test_subscribe_bmc_skips_when_password_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("BMC_PASSWORD", raising=False)
    from amzn_cse_telco_autonomous_network_agents_app.agent import redfish_events

    def _should_not_be_called(*_a, **_kw):
        raise AssertionError("curl_bmc must not be invoked when BMC_PASSWORD is unset")

    # subscribe_bmc delegates to util.bmc.curl_bmc; patch there (patching
    # redfish_events.subprocess would never fire) so the early-return guard is
    # genuinely exercised.
    with patch("amzn_cse_telco_autonomous_network_agents_app.agent.util.bmc.curl_bmc", side_effect=_should_not_be_called), patch.object(redfish_events.log, "error") as mock_error:
        result = redfish_events.subscribe_bmc(_fake_bmc_node(), "https://anra/webhook")

    assert result is None
    mock_error.assert_called_once()
    assert "BMC_PASSWORD" in mock_error.call_args.args[0]
