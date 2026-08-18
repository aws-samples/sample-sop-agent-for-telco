# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Regression tests for the provisioning router CR emission (P0.1 follow-up).

The POST /api/provisioning/requests endpoint had the same wrong API group
that discovery.py had — fixed alongside Phase 1 cleanup.
"""

from dataclasses import dataclass
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from amzn_cse_telco_autonomous_network_agents_app.agent.routers.provisioning import router


@dataclass
class FakeR:
    stdout: str = ""
    stderr: str = ""
    returncode: int = 0
    @property
    def success(self) -> bool: return self.returncode == 0


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


@patch("amzn_cse_telco_autonomous_network_agents_app.agent.routers.provisioning.run_cmd")
def test_provisioning_request_uses_correct_api_group(mock_run, client):
    """The CR emitted by POST /api/provisioning/requests must match the installed CRD group."""
    captured = {}

    def side_effect(cmd, **_):
        # The endpoint writes YAML to a tempfile and applies it.
        if cmd.startswith("kubectl apply -f "):
            path = cmd.split("kubectl apply -f ", 1)[1].strip()
            try:
                with open(path) as f:
                    captured["yaml"] = f.read()
            except FileNotFoundError:
                pass
        return FakeR(stdout="provisioningrequest.provisioning.anpa.aws.io/x created")

    mock_run.side_effect = side_effect
    resp = client.post(
        "/api/provisioning/requests",
        json={"hostname": "test-host", "bmcAddress": "192.168.30.10"},
    )
    assert resp.status_code in (200, 201, 202)
    body = captured.get("yaml", "")
    assert "apiVersion: provisioning.anpa.aws.io/v1alpha1" in body
    assert "anpa.eks-hybrid.amazonaws.com" not in body, "old (broken) group must not appear"
    assert 'provisioning.anpa.aws.io/managed: "true"' in body



# ============================================================================
# Phase 4.3 — GET /api/provisioning/requests/{name}/diagnosis
# ============================================================================


def _make_client():
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_diagnosis_endpoint_returns_persisted_record(tmp_path, monkeypatch):
    monkeypatch.setenv("ANPA_DIAGNOSIS_DIR", str(tmp_path))
    import importlib
    import amzn_cse_telco_autonomous_network_agents_app.agent.agents.anpa.failure_handler as fh
    importlib.reload(fh)
    fh._persist_diagnosis("anpa-system", "rq-1", {
        "name": "rq-1", "namespace": "anpa-system",
        "phase": "Provisioning", "diagnosis": "ROOT CAUSE: x",
        "source": "ai", "hostnames": ["server-1"], "error": "e",
    })
    r = _make_client().get("/api/provisioning/requests/rq-1/diagnosis")
    assert r.status_code == 200
    body = r.json()
    assert body["source"] == "ai"
    assert "ROOT CAUSE" in body["diagnosis"]


def test_diagnosis_endpoint_404_when_no_record(tmp_path, monkeypatch):
    monkeypatch.setenv("ANPA_DIAGNOSIS_DIR", str(tmp_path))
    import importlib
    import amzn_cse_telco_autonomous_network_agents_app.agent.agents.anpa.failure_handler as fh
    importlib.reload(fh)
    r = _make_client().get("/api/provisioning/requests/never-failed/diagnosis")
    assert r.status_code == 404
