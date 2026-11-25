"""/api/anda/fleet-opinions reports NF health from Deployments.

Mission Control's NF grid colours tiles Running / Degraded / Down. The endpoint
must use those values, keep a scaled-to-zero NF in the list, skip Jobs and
MongoDB, and never invent NFs when the cluster cannot be read.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from amzn_cse_telco_autonomous_network_agents_app.agent.core import executor
from amzn_cse_telco_autonomous_network_agents_app.agent.routers import agents


def _deploy(name, desired, available):
    status = {"availableReplicas": available} if available else {}
    return {"metadata": {"name": name}, "spec": {"replicas": desired}, "status": status}


@pytest.fixture
def kubectl(monkeypatch):
    calls = []

    def install(items=None, success=True, stdout=None):
        def fake_run_cmd(cmd, timeout=None):
            calls.append(cmd)
            out = stdout if stdout is not None else json.dumps({"items": items or []})
            return SimpleNamespace(success=success, stdout=out)

        monkeypatch.setattr(executor, "run_cmd", fake_run_cmd)
        return calls

    monkeypatch.setenv("DEFAULT_NF_NAMESPACE", "free5gc")
    return install


HEALTHY = [
    _deploy("free5gc-amf-deployment", 1, 1),
    _deploy("free5gc-smf-deployment", 1, 1),
    _deploy("free5gc-upf-deployment", 1, 1),
    _deploy("free5gc-mongodb", 1, 1),
    _deploy("packetrusher-packetrusher", 1, 1),
]


def test_healthy_network_is_all_running_with_nf_names(kubectl):
    calls = kubectl(HEALTHY)
    nfs = agents.get_fleet_opinions()["nfs"]
    assert calls == ["kubectl get deployments -n free5gc -o json"]
    assert [n["name"] for n in nfs] == ["AMF", "SMF", "UPF", "gNB/UE sim"]
    assert {n["status"] for n in nfs} == {"Running"}
    assert all("mongodb" not in n["deployment"] for n in nfs)


def test_amf_scaled_to_zero_stays_listed_as_down(kubectl):
    items = [_deploy("free5gc-amf-deployment", 0, 0)] + HEALTHY[1:]
    kubectl(items)
    amf = next(n for n in agents.get_fleet_opinions()["nfs"] if n["name"] == "AMF")
    assert amf["status"] == "Down"
    assert amf["detail"] == "0/0 available"


def test_not_ready_pod_is_down_and_partial_is_degraded(kubectl):
    kubectl([_deploy("free5gc-smf-deployment", 1, 0), _deploy("free5gc-upf-deployment", 2, 1)])
    by_name = {n["name"]: n["status"] for n in agents.get_fleet_opinions()["nfs"]}
    assert by_name == {"SMF": "Down", "UPF": "Degraded"}


@pytest.mark.parametrize("kwargs", [{"success": False}, {"stdout": "not json"}])
def test_unreadable_cluster_returns_no_invented_nfs(kubectl, kwargs):
    kubectl(**kwargs)
    result = agents.get_fleet_opinions()
    assert result["nfs"] == []
    assert result["error"] == "NF status unavailable"
