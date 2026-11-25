"""A remediation scoped to a layer ("core") is checked namespace-wide.

ANRA names the plan's NF "core" for free5gc_registration_unavailable. No pod is
labelled app=core, so the per-NF check reported "No pods found" and marked a
successful remediation PartiallyFailed.
"""

from __future__ import annotations

import json

from amzn_cse_telco_autonomous_network_agents_app.agent.agents.anda import validation


def _pod(name, phase="Running", ready=True, job=False):
    meta = {"name": name}
    if job:
        meta["ownerReferences"] = [{"kind": "Job"}]
    return {"metadata": meta, "status": {"phase": phase, "containerStatuses": [{"ready": ready}]}}


def _fake(monkeypatch, pods):
    calls = []

    def kubectl(args, timeout=30):
        calls.append(args)
        if args.startswith("get service"):
            return 1, "", "not found"
        return 0, json.dumps({"items": pods}), ""

    monkeypatch.setattr(validation, "_kubectl", kubectl)
    return calls


def test_core_scope_passes_when_the_namespace_is_healthy(monkeypatch):
    calls = _fake(monkeypatch, [_pod("free5gc-amf-x"), _pod("packetrusher-y"), _pod("subprov-z", "Succeeded", False, True)])
    result = validation.postdeploy_check("core", "free5gc")
    assert result["status"] == "ok", result
    assert all("-l " not in c for c in calls)


def test_core_scope_fails_when_a_pod_is_not_ready(monkeypatch):
    _fake(monkeypatch, [_pod("free5gc-amf-x"), _pod("packetrusher-y", ready=False)])
    result = validation.postdeploy_check("core", "free5gc")
    assert result["status"] == "failed"
    assert "packetrusher-y" in " ".join(str(i) for i in result["issues"])


def test_concrete_nf_still_uses_its_label(monkeypatch):
    calls = _fake(monkeypatch, [])
    result = validation.postdeploy_check("amf", "free5gc")
    assert result["status"] == "failed"
    assert any("-l app=amf" in c for c in calls)
