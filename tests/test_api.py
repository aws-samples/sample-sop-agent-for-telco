from datetime import datetime

import pytest
from fastapi.testclient import TestClient

# Importing the api module triggers create_app(role=os.getenv("AGENT_ROLE", "anra"))
# at module load. We import lazily inside each test so the AGENT_ROLE env can be
# controlled per-test without re-import gymnastics.


def _fresh_app(role: str):
    from amzn_cse_telco_autonomous_network_agents_app.agent.api import create_app
    return create_app(role=role)


def _make_static_dir(tmp_path):
    """Create a minimal built-frontend layout (index.html + assets/)."""
    (tmp_path / "assets").mkdir()
    (tmp_path / "index.html").write_text("<!doctype html><title>ANO</title>")
    (tmp_path / "assets" / "app.js").write_text("console.log('ano');")
    return tmp_path


def test_anra_serves_webui_from_static_dir(tmp_path, monkeypatch) -> None:
    # Regression: the WebUI was silently not served because the Dockerfile put
    # the build at /app/static while the app looked inside the installed
    # package. STATIC_DIR must make ANRA serve index.html + /assets.
    static = _make_static_dir(tmp_path)
    monkeypatch.setenv("STATIC_DIR", str(static))
    client = TestClient(_fresh_app("anra"))

    root = client.get("/")
    assert root.status_code == 200
    assert "<title>ANO</title>" in root.text

    asset = client.get("/assets/app.js")
    assert asset.status_code == 200
    assert "console.log" in asset.text

    # Unknown client-side route falls back to index.html (SPA behavior).
    spa = client.get("/some/deep/route")
    assert spa.status_code == 200
    assert "<title>ANO</title>" in spa.text


def test_static_dir_traversal_is_blocked(tmp_path, monkeypatch) -> None:
    static = _make_static_dir(tmp_path)
    monkeypatch.setenv("STATIC_DIR", str(static))
    client = TestClient(_fresh_app("anra"))
    # Path traversal must not escape the static root; falls back to index.html.
    resp = client.get("/../../etc/hostname")
    assert resp.status_code == 200
    assert "<title>ANO</title>" in resp.text


@pytest.mark.parametrize("role", ["anda", "anpa"])
def test_non_anra_roles_do_not_serve_webui(tmp_path, monkeypatch, role: str) -> None:
    # The dashboard UI is ANRA-only; other roles must not mount it even when a
    # static dir is present.
    static = _make_static_dir(tmp_path)
    monkeypatch.setenv("STATIC_DIR", str(static))
    client = TestClient(_fresh_app(role))
    assert client.get("/").status_code == 404


def test_health_returns_ok_with_timestamp() -> None:
    client = TestClient(_fresh_app("anra"))
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    # Timestamp must parse as ISO-8601.
    datetime.fromisoformat(body["timestamp"].replace("Z", "+00:00"))


@pytest.mark.parametrize("role", ["anra", "anda", "anpa"])
def test_create_app_returns_fastapi_for_each_role(role: str) -> None:
    app = _fresh_app(role)
    assert app is not None
    # Title encodes the role.
    assert role.upper() in app.title


def test_anra_role_app_serves_health() -> None:
    """ANRA-mode app must always have /health since it's a SHARED router."""
    app = _fresh_app("anra")
    routes = {r.path for r in app.routes}
    assert "/health" in routes


def test_unknown_role_does_not_crash_create_app() -> None:
    """Upstream design: unknown role falls back to shared routers only, no crash."""
    app = _fresh_app("blarg")
    assert app is not None
    routes = {r.path for r in app.routes}
    # Shared routers always register; /health proves the factory survived.
    assert "/health" in routes


# ── CORS allowlist ──


def _parse_origins():
    from amzn_cse_telco_autonomous_network_agents_app.agent.api import (
        _parse_cors_origins,
    )
    return _parse_cors_origins()


def test_cors_default_is_empty_allowlist(monkeypatch: pytest.MonkeyPatch) -> None:
    """Unset env: deny all cross-origin. The dashboard control plane drives
    kubectl/SSM/Redfish; cross-origin requests must be opted in by an
    operator at deploy time, never the default."""
    monkeypatch.delenv("CORS_ALLOW_ORIGINS", raising=False)
    monkeypatch.delenv("CORS_DEV", raising=False)
    assert _parse_origins() == []


@pytest.mark.parametrize("truthy", ["1", "true", "yes", "on", "TRUE", "Yes", "ON"])
def test_cors_dev_truthy_values_open_to_wildcard(
    truthy: str,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """CORS_DEV accepts a small truthy set (case-insensitive) so devs setting
    CORS_DEV=true don't silently fall through to default-deny. Each variant
    emits a loud warning so the flag is visible in logs if it ever leaks
    into a production env."""
    monkeypatch.setenv("CORS_DEV", truthy)
    monkeypatch.delenv("CORS_ALLOW_ORIGINS", raising=False)
    import logging
    with caplog.at_level(logging.WARNING):
        result = _parse_origins()
    assert result == ["*"]
    assert any("CORS_DEV" in rec.message for rec in caplog.records)


def test_cors_dev_unrecognized_value_warns_and_falls_through(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A typo or unrecognized truthy value (e.g. CORS_DEV=enabled) must NOT
    silently fall through — log a warning so the dev sees their flag was
    ignored and can fix it."""
    monkeypatch.setenv("CORS_DEV", "enabled")
    monkeypatch.delenv("CORS_ALLOW_ORIGINS", raising=False)
    import logging
    with caplog.at_level(logging.WARNING):
        result = _parse_origins()
    assert result == []  # falls through to default-deny
    assert any("not recognized" in rec.message for rec in caplog.records)


def test_cors_explicit_allowlist(monkeypatch: pytest.MonkeyPatch) -> None:
    """Comma-separated allowlist parses; whitespace and empty entries
    are stripped."""
    monkeypatch.setenv(
        "CORS_ALLOW_ORIGINS",
        "https://anra.example.com, https://anra-staging.example.com,, https://localhost:3000 ",
    )
    monkeypatch.delenv("CORS_DEV", raising=False)
    result = _parse_origins()
    assert result == [
        "https://anra.example.com",
        "https://anra-staging.example.com",
        "https://localhost:3000",
    ]


def test_cors_dev_overrides_explicit_allowlist(monkeypatch: pytest.MonkeyPatch) -> None:
    """CORS_DEV=1 wins over CORS_ALLOW_ORIGINS — dev opt-in is a hard
    override so a developer setting it locally doesn't have to also
    clear the prod allowlist."""
    monkeypatch.setenv("CORS_DEV", "1")
    monkeypatch.setenv("CORS_ALLOW_ORIGINS", "https://anra.example.com")
    assert _parse_origins() == ["*"]


# ── /health auth bypass ──


def _is_bypass(path: str) -> bool:
    from amzn_cse_telco_autonomous_network_agents_app.agent.api import _is_auth_bypass
    return _is_auth_bypass(path)


def test_auth_bypass_health_root() -> None:
    assert _is_bypass("/health") is True


def test_auth_bypass_health_trailing_slash() -> None:
    """k8s probes sometimes hit /health/ — must not 401."""
    assert _is_bypass("/health/") is True


def test_auth_bypass_health_live_and_ready() -> None:
    """Common k8s liveness/readiness probe variants — must not 401."""
    assert _is_bypass("/health/live") is True
    assert _is_bypass("/health/ready") is True
    assert _is_bypass("/health/live/") is True


def test_auth_bypass_does_not_match_unrelated_paths() -> None:
    """The bypass set is closed: only /health, /health/live, /health/ready
    (with trailing slashes normalized). Anything else MUST require auth.
    The boundary cases below are what a future refactor (lower-casing,
    prefix-loosening, separator-relaxing) would silently re-open."""
    # Different prefix entirely.
    assert _is_bypass("/api/health") is False
    assert _is_bypass("/api/alarms") is False
    assert _is_bypass("/") is False
    assert _is_bypass("") is False
    # Case-sensitive contract — kubelet probes use lowercase exclusively.
    assert _is_bypass("/HEALTH") is False
    assert _is_bypass("/Health") is False
    assert _is_bypass("/Health/Live") is False
    # Separator must be '/', not '-' or other.
    assert _is_bypass("/health-foo") is False
    assert _is_bypass("/healthz") is False  # different word, not a sub-path
    # Sub-paths under /health that aren't in the closed set MUST require auth.
    # Without the closed-set fix, /health/foo would slip through and combined
    # with the SPA catch-all would serve index.html unauthenticated.
    assert _is_bypass("/health/foo") is False
    assert _is_bypass("/health/admin") is False
    assert _is_bypass("/health/live/extra") is False
