# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Tests for detection.* alert-source toggles (config, monitor, Helm)."""

import shutil
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from amzn_cse_telco_autonomous_network_agents_app.agent.config import DetectionConfig, SiteConfig, load_config

MONITOR = "amzn_cse_telco_autonomous_network_agents_app.agent.monitor"
OTHER_SOURCES = (
    "evaluate_ran_thresholds",
    "evaluate_os_thresholds",
    "fetch_alertmanager_alerts",
    "poll_redfish_sel",
    "poll_cloudwatch_k8s_events",
    "evaluate_dynamic_anomalies",
)
CHART_DIR = Path(__file__).resolve().parent.parent / "helm-charts" / "anra"
COMMON_CHART_DIR = Path(__file__).resolve().parent.parent / "helm-charts" / "anra-common"


def test_load_config_honours_disabled_poller(tmp_path):
    path = tmp_path / "agent-config.yaml"
    path.write_text(yaml.safe_dump({"detection": {"k8s_pod_health": False, "unknown_flag": 1}}))
    assert load_config(str(path)).detection.k8s_pod_health is False


def test_load_config_without_detection_keeps_default(tmp_path):
    path = tmp_path / "agent-config.yaml"
    path.write_text(yaml.safe_dump({"cluster": {"name": "c1"}}))
    assert load_config(str(path)).detection.k8s_pod_health is True


def _collect(cfg):
    from amzn_cse_telco_autonomous_network_agents_app.agent import monitor

    pod_alert = {"name": "nf_crashloop"}
    with patch(f"{MONITOR}.poll_k8s_pod_health", return_value=[pod_alert]) as poller:
        patches = [patch(f"{MONITOR}.{name}", return_value=[]) for name in OTHER_SOURCES]
        for p in patches:
            p.start()
        try:
            alerts = monitor._collect_alerts(cfg)
        finally:
            for p in patches:
                p.stop()
    return alerts, poller


def test_collect_alerts_skips_pod_health_when_disabled():
    cfg = SiteConfig(detection=DetectionConfig(k8s_pod_health=False))
    alerts, poller = _collect(cfg)
    poller.assert_not_called()
    assert alerts == []


def test_collect_alerts_polls_pod_health_by_default():
    alerts, poller = _collect(SiteConfig())
    poller.assert_called_once()
    assert alerts == [{"name": "nf_crashloop"}]


@pytest.fixture
def anra_chart_deps():
    dep_dir = CHART_DIR / "charts" / "anra-common"
    created = not dep_dir.exists() and COMMON_CHART_DIR.exists()
    if created:
        shutil.copytree(str(COMMON_CHART_DIR), str(dep_dir))
    yield
    if created and dep_dir.exists():
        shutil.rmtree(str(dep_dir))


def _rendered_agent_config(*args):
    cmd = ["helm", "template", "anra", str(CHART_DIR), "--namespace", "anra", *args]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, f"helm template failed: {r.stderr}"
    for doc in yaml.safe_load_all(r.stdout):
        if doc and doc.get("kind") == "ConfigMap" and "agent-config.yaml" in doc.get("data", {}):
            return yaml.safe_load(doc["data"]["agent-config.yaml"])
    pytest.fail("agent-config.yaml ConfigMap not rendered")


@pytest.mark.skipif(shutil.which("helm") is None, reason="helm not installed")
@pytest.mark.usefixtures("anra_chart_deps")
def test_helm_renders_detection_block():
    assert _rendered_agent_config()["detection"] == {"k8s_pod_health": True}
    workshop_values = Path(__file__).resolve().parent.parent / "configs" / "free5gc-monitoring" / "anra-values.yaml"
    assert _rendered_agent_config("-f", str(workshop_values))["detection"] == {"k8s_pod_health": False}
