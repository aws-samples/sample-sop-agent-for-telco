import pytest

# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Integration test for /api/inventory/{hostname}/readiness — Phase 2.4."""

import json
from dataclasses import dataclass
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from amzn_cse_telco_autonomous_network_agents_app.agent.routers.inventory import router


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


HWI_BODY = json.dumps({
    "metadata": {"name": "mi-test"},
    "spec": {
        "hostname": "mi-test",
        "bmcAddress": "192.168.30.10",
        "systemUUID": "uuid-1",
        "serialNumber": "7WZ56G4",
        "cpu": {"cores": 64},
        "memory": {"totalGiB": 256},
    },
})

LIVE_BIOS = {
    "Attributes": {
        "BootMode": "Uefi",
        "SriovGlobalEnable": "Enabled",
        "ProcCStates": "Disabled",
        "EnergyPerformanceBias": "MaxPower",
        "LogicalProc": "Enabled",
        "MemFrequency": "MaxPerf",
        "SubNumaCluster": "Disabled",
    }
}


@patch("amzn_cse_telco_autonomous_network_agents_app.agent.agents.anpa.bios_inspector.run_cmd")
@patch("amzn_cse_telco_autonomous_network_agents_app.agent.routers.inventory.run_cmd")
@pytest.mark.skip(reason="inventory/readiness endpoint not yet ported")
def test_readiness_returns_structured_report(router_run, bios_run, client):
    router_run.return_value = FakeR(stdout=HWI_BODY)
    # bios_inspector makes 2 curls: bios attrs + firmware listing
    bios_run.side_effect = [
        FakeR(stdout=json.dumps(LIVE_BIOS)),
        FakeR(stdout=json.dumps({"Members": []})),
    ]
    r = client.get("/api/inventory/mi-test/readiness?nf=upf")
    assert r.status_code == 200
    body = r.json()
    assert body["nf"] == "upf"
    assert body["hostname"] == "mi-test"
    assert "ready" in body
    assert isinstance(body["gaps"], list)
    assert "summary" in body and "explanation" in body


@patch("amzn_cse_telco_autonomous_network_agents_app.agent.routers.inventory.run_cmd")
def test_readiness_unknown_nf_returns_404(router_run, client):
    r = client.get("/api/inventory/mi-test/readiness?nf=does-not-exist")
    assert r.status_code == 404
    assert "profile" in r.json()["detail"].lower()


@patch("amzn_cse_telco_autonomous_network_agents_app.agent.routers.inventory.run_cmd")
def test_readiness_unknown_host_returns_404(router_run, client):
    router_run.return_value = FakeR(returncode=1, stderr="hardwareinventory not found")
    r = client.get("/api/inventory/ghost/readiness?nf=upf")
    assert r.status_code == 404


@patch("amzn_cse_telco_autonomous_network_agents_app.agent.agents.anpa.bios_inspector.run_cmd")
@patch("amzn_cse_telco_autonomous_network_agents_app.agent.routers.inventory.run_cmd")
@pytest.mark.skip(reason="inventory/readiness endpoint not yet ported")
def test_readiness_no_bmc_address_returns_409(router_run, bios_run, client):
    router_run.return_value = FakeR(stdout=json.dumps({
        "metadata": {"name": "x"}, "spec": {"hostname": "x"}
    }))
    r = client.get("/api/inventory/x/readiness?nf=upf")
    assert r.status_code == 409
