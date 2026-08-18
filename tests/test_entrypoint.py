import os
from unittest.mock import patch

import pytest

from amzn_cse_telco_autonomous_network_agents_app.agent.entrypoint import (
    _check_dependencies,
    _parse_log_level,
    _parse_port,
    _parse_role,
    main,
    run_background,
)

# ── _parse_port ──


def test_parse_port_accepts_valid() -> None:
    assert _parse_port("8080") == 8080
    assert _parse_port("  8080  ") == 8080
    assert _parse_port("1") == 1
    assert _parse_port("65535") == 65535


def test_parse_port_rejects_non_integer() -> None:
    with pytest.raises(SystemExit, match="must be an integer"):
        _parse_port("foo")


def test_parse_port_rejects_out_of_range() -> None:
    with pytest.raises(SystemExit, match="between 1 and 65535"):
        _parse_port("0")
    with pytest.raises(SystemExit, match="between 1 and 65535"):
        _parse_port("65536")
    with pytest.raises(SystemExit, match="between 1 and 65535"):
        _parse_port("-1")


# ── _parse_log_level ──


def test_parse_log_level_accepts_valid() -> None:
    assert _parse_log_level("DEBUG") == "debug"
    assert _parse_log_level("  warning  ") == "warning"
    for level in ("critical", "error", "warning", "info", "debug", "trace"):
        assert _parse_log_level(level) == level


def test_parse_log_level_falls_back_on_unknown(capsys: pytest.CaptureFixture[str]) -> None:
    assert _parse_log_level("verbose") == "info"
    captured = capsys.readouterr()
    assert "LOG_LEVEL='verbose' not recognized" in captured.err
    assert "falling back to info" in captured.err


# ── _parse_role ──


def test_parse_role_accepts_valid() -> None:
    assert _parse_role("anra") == "anra"
    assert _parse_role("ANDA") == "anda"
    assert _parse_role("  anpa  ") == "anpa"


def test_parse_role_rejects_unknown() -> None:
    with pytest.raises(SystemExit, match="AGENT_ROLE must be one of"):
        _parse_role("blarg")


# ── main() — patches uvicorn.run + threading.Thread so no server actually starts ──


def test_main_starts_uvicorn_with_parsed_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGENT_ROLE", "anra")
    monkeypatch.setenv("PORT", "9000")
    monkeypatch.setenv("LOG_LEVEL", "debug")

    with patch("uvicorn.run") as mock_run, \
         patch("amzn_cse_telco_autonomous_network_agents_app.agent.entrypoint._validate_config") as mock_validate, \
         patch("amzn_cse_telco_autonomous_network_agents_app.agent.entrypoint.threading.Thread") as mock_thread, \
         patch("amzn_cse_telco_autonomous_network_agents_app.agent.api.create_app") as mock_create_app:
        mock_create_app.return_value = "FAKE_APP"
        main()

    mock_validate.assert_called_once_with("anra")
    mock_create_app.assert_called_once_with(role="anra")
    mock_thread.assert_called_once()
    assert mock_thread.call_args.kwargs["args"] == ("anra",)
    assert mock_thread.call_args.kwargs["daemon"] is True
    mock_thread.return_value.start.assert_called_once()
    mock_run.assert_called_once_with(
        "FAKE_APP",
        host="0.0.0.0",  # noqa: S104
        port=9000,
        log_level="debug",
    )


def test_main_uses_defaults_when_env_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AGENT_ROLE", raising=False)
    monkeypatch.delenv("PORT", raising=False)
    monkeypatch.delenv("LOG_LEVEL", raising=False)

    with patch("uvicorn.run") as mock_run, \
         patch("amzn_cse_telco_autonomous_network_agents_app.agent.entrypoint._validate_config"), \
         patch("amzn_cse_telco_autonomous_network_agents_app.agent.entrypoint.threading.Thread"), \
         patch("amzn_cse_telco_autonomous_network_agents_app.agent.api.create_app") as mock_create_app:
        mock_create_app.return_value = "FAKE_APP"
        main()

    mock_create_app.assert_called_once_with(role="anra")
    mock_run.assert_called_once_with(
        "FAKE_APP",
        host="0.0.0.0",  # noqa: S104
        port=8080,
        log_level="info",
    )


# ── run_background — verify lazy imports resolve for each role ──
# These guard against import-rewrite typos: a missing module or wrong
# namespace in any of the three role paths would ship green without these.


def test_run_background_anra_invokes_run_loop(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("REDFISH_WEBHOOK_PORT", raising=False)
    with patch("amzn_cse_telco_autonomous_network_agents_app.agent.monitor.run_loop") as mock_loop:
        run_background("anra")
    mock_loop.assert_called_once_with()
    # ANRA role defaults the webhook port for the redfish listener.
    assert os.environ.get("REDFISH_WEBHOOK_PORT") == "8081"


def test_run_background_anda_invokes_orchestrator() -> None:
    with patch(
        "amzn_cse_telco_autonomous_network_agents_app.agent.agents.anda.orchestrator.run_orchestrator",
    ) as mock_orch:
        run_background("anda")
    mock_orch.assert_called_once_with()


def test_run_background_anpa_invokes_reconciler() -> None:
    with patch(
        "amzn_cse_telco_autonomous_network_agents_app.agent.agents.anpa.reconciler.run_reconciler",
    ) as mock_rec:
        run_background("anpa")
    mock_rec.assert_called_once_with()


def test_run_background_crashes_call_os_exit() -> None:
    """Crash trap must force pod restart so /health doesn't lie about liveness."""
    with patch(
        "amzn_cse_telco_autonomous_network_agents_app.agent.monitor.run_loop",
        side_effect=RuntimeError("simulated crash"),
    ), patch("os._exit") as mock_exit:
        run_background("anra")
    mock_exit.assert_called_once_with(1)


# ── _check_dependencies — non-fatal startup connectivity checks ──


class TestCheckDependencies:
    """Verify _check_dependencies logs warnings but never crashes."""

    def _make_cfg(self, **kwargs):
        from amzn_cse_telco_autonomous_network_agents_app.agent.config import SiteConfig
        return SiteConfig(
            cluster_name="test",
            cluster_region="us-west-1",
            bedrock_region="us-west-2",
            influxdb_url=kwargs.get("influxdb_url", ""),
            alertmanager_url=kwargs.get("alertmanager_url", ""),
            argocd_url=kwargs.get("argocd_url", ""),
            tinkerbell_namespace=kwargs.get("tinkerbell_namespace", "tink-system"),
        )

    def test_anra_checks_influxdb_and_alertmanager(self, caplog):
        """ANRA role checks InfluxDB + Alertmanager + kubectl."""
        cfg = self._make_cfg(influxdb_url="http://fake:8086", alertmanager_url="http://fake:9093")
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = type("R", (), {"returncode": 1})()
            _check_dependencies("anra", cfg)
        assert "InfluxDB" in caplog.text
        assert "Alertmanager" in caplog.text
        assert "Kubernetes API" in caplog.text

    def test_anpa_checks_tinkerbell_namespace(self, caplog):
        """ANPA role checks Tinkerbell namespace + kubectl."""
        import logging
        cfg = self._make_cfg(tinkerbell_namespace="tink-system")
        with caplog.at_level(logging.INFO, logger="entrypoint"), \
             patch("subprocess.run") as mock_run:
            mock_run.return_value = type("R", (), {"returncode": 0})()
            _check_dependencies("anpa", cfg)
        assert "Tinkerbell" in caplog.text
        assert "Kubernetes API" in caplog.text

    def test_anda_checks_argocd(self, caplog):
        """ANDA role checks ArgoCD + kubectl."""
        cfg = self._make_cfg(argocd_url="http://argocd:80")
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = type("R", (), {"returncode": 1})()
            _check_dependencies("anda", cfg)
        assert "ArgoCD" in caplog.text

    def test_never_crashes_on_exception(self, caplog):
        """Even if all checks throw, the function completes without raising."""
        cfg = self._make_cfg(influxdb_url="http://fake:8086")
        with patch("subprocess.run", side_effect=Exception("timeout")), \
             patch("urllib.request.urlopen", side_effect=Exception("refused")):
            _check_dependencies("anra", cfg)
        assert "unreachable" in caplog.text

    def test_successful_check_logs_reachable(self, caplog):
        """Reachable endpoint logs ✓."""
        import logging
        cfg = self._make_cfg()
        with caplog.at_level(logging.INFO, logger="entrypoint"), \
             patch("subprocess.run") as mock_run:
            mock_run.return_value = type("R", (), {"returncode": 0})()
            _check_dependencies("anra", cfg)
        assert "reachable" in caplog.text
