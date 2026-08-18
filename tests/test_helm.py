# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Tests for Helm chart — validates ANRA-only template rendering."""
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.skipif(shutil.which("helm") is None, reason="helm not installed")

CHART_DIR = Path(__file__).resolve().parent.parent / "helm-charts" / "anra"
COMMON_CHART_DIR = Path(__file__).resolve().parent.parent / "helm-charts" / "anra-common"


@pytest.fixture(autouse=True, scope="session")
def ensure_chart_deps():
    """Ensure anra-common dependency is available locally for helm template."""
    dep_dir = CHART_DIR / "charts" / "anra-common"
    if not dep_dir.exists() and COMMON_CHART_DIR.exists():
        dep_dir.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(str(COMMON_CHART_DIR), str(dep_dir))
    yield
    # Cleanup: remove copied chart after tests
    if dep_dir.exists():
        shutil.rmtree(str(dep_dir))


def helm_template(*args):
    cmd = ["helm", "template", "anra", str(CHART_DIR), "--namespace", "anra"] + list(args)
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, f"helm template failed: {r.stderr}"
    docs = list(yaml.safe_load_all(r.stdout))
    return [d for d in docs if d]


def get_resource(docs, kind, name=None):
    for d in docs:
        if d.get("kind") == kind:
            if name is None or d["metadata"]["name"] == name:
                return d
    return None


class TestCoreResources:
    def test_deployment_exists(self):
        docs = helm_template("--set", "image.repository=test")
        assert get_resource(docs, "Deployment", "anra") is not None

    def test_config_configmap(self):
        docs = helm_template("--set", "image.repository=test")
        cm = get_resource(docs, "ConfigMap", "anra-config")
        assert cm is not None
        cfg = yaml.safe_load(cm["data"]["agent-config.yaml"])
        assert "cluster" in cfg

    def test_config_has_monitoring(self):
        docs = helm_template("--set", "image.repository=test", "--set", "monitoring.influxdbUrl=http://x:8086")
        cm = get_resource(docs, "ConfigMap", "anra-config")
        cfg = yaml.safe_load(cm["data"]["agent-config.yaml"])
        assert cfg["monitoring"]["influxdb_url"] == "http://x:8086"


class TestNoWorkloadTemplates:
    def test_no_influxdb(self):
        docs = helm_template("--set", "image.repository=test")
        assert get_resource(docs, "StatefulSet") is None

    def test_no_telegraf(self):
        docs = helm_template("--set", "image.repository=test")
        kinds = [d["kind"] for d in docs]
        assert kinds.count("Deployment") == 1

    def test_no_prometheusrule(self):
        docs = helm_template("--set", "image.repository=test")
        assert get_resource(docs, "PrometheusRule") is None


class TestConfigRendering:
    def test_nodes_rendered(self):
        docs = helm_template("--set", "image.repository=test", "--set", "config.nodes[0].name=w1")
        cm = get_resource(docs, "ConfigMap", "anra-config")
        cfg = yaml.safe_load(cm["data"]["agent-config.yaml"])
        assert cfg["nodes"][0]["name"] == "w1"

    def test_external_influx_url(self):
        docs = helm_template("--set", "image.repository=test", "--set", "monitoring.influxdbUrl=http://ext:8086")
        dep = get_resource(docs, "Deployment", "anra")
        envs = {e["name"]: e.get("value", "") for e in dep["spec"]["template"]["spec"]["containers"][0]["env"]}
        assert envs["INFLUX_URL"] == "http://ext:8086"

    def test_approval_mode(self):
        docs = helm_template("--set", "image.repository=test", "--set", "approval.mode=auto")
        dep = get_resource(docs, "Deployment", "anra")
        envs = {e["name"]: e.get("value", "") for e in dep["spec"]["template"]["spec"]["containers"][0]["env"]}
        assert envs["APPROVAL_MODE"] == "auto"


class TestAgentRole:
    def test_agent_role_env_set(self):
        docs = helm_template("--set", "image.repository=test")
        dep = get_resource(docs, "Deployment", "anra")
        envs = {e["name"]: e.get("value", "") for e in dep["spec"]["template"]["spec"]["containers"][0]["env"]}
        assert envs["AGENT_ROLE"] == "anra"


class TestConfigsDirectory:
    def test_open5gs_values(self):
        p = Path(__file__).parent.parent / "configs" / "open5gs" / "values.yaml"
        assert p.exists()
        yaml.safe_load(p.read_text())

    def test_telegraf_collector(self):
        p = Path(__file__).parent.parent / "configs" / "telegraf" / "core_collector.py"
        assert p.exists()
