# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""postdeploy_check must find NF pods regardless of the chart's label convention."""

import json

from amzn_cse_telco_autonomous_network_agents_app.agent.agents.anda import validation


def _running_pod(name):
    return {
        "metadata": {"name": name},
        "status": {
            "phase": "Running",
            "containerStatuses": [{"name": "c", "ready": True, "restartCount": 0}],
        },
    }


def _fake_kubectl(pods_by_selector):
    """Return a _kubectl stub answering `get pods -l <sel>` from the given map."""

    def run(args):
        sel = args.split(" -l ", 1)[1].split()[0] if " -l " in args else ""
        if "get pods" in args:
            pods = pods_by_selector.get(sel, [])
            if "-o name" in args:
                return 0, "\n".join(f"pod/{p['metadata']['name']}" for p in pods), ""
            return 0, json.dumps({"items": pods}), ""
        if "get endpoints" in args:
            return 0, json.dumps({"items": []}), ""
        return 1, "", "unexpected"

    return run


class TestNfPodSelector:
    def test_free5gc_epc_mode_label_is_found(self, monkeypatch):
        monkeypatch.setattr(
            validation, "_kubectl", _fake_kubectl({"epc-mode=amf": [_running_pod("free5gc-amf-deployment-x")]})
        )
        assert validation._nf_pod_selector("amf", "free5gc") == "epc-mode=amf"
        result = validation.postdeploy_check("amf", "free5gc")
        assert result["status"] == "ok", result

    def test_open5gs_app_label_still_preferred(self, monkeypatch):
        monkeypatch.setattr(
            validation,
            "_kubectl",
            _fake_kubectl({"app=amf": [_running_pod("open5gs-amf-1")], "epc-mode=amf": [_running_pod("other")]}),
        )
        assert validation._nf_pod_selector("amf", "open5gs") == "app=amf"

    def test_no_pods_reports_primary_convention(self, monkeypatch):
        monkeypatch.setattr(validation, "_kubectl", _fake_kubectl({}))
        result = validation.postdeploy_check("amf", "free5gc")
        assert result["status"] == "failed"
        assert any("app=amf" in i for i in result["issues"])
