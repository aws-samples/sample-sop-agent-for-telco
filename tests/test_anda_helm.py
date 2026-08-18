# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Tests for ANDA Helm chart — validates template rendering."""

import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.skipif(shutil.which("helm") is None, reason="helm not installed")

CHART_DIR = Path(__file__).resolve().parent.parent / "helm-charts" / "anda"
COMMON_CHART_DIR = Path(__file__).resolve().parent.parent / "helm-charts" / "anra-common"


@pytest.fixture(autouse=True, scope="session")
def ensure_chart_deps():
    """Ensure anra-common dependency is available locally for helm template."""
    dep_dir = CHART_DIR / "charts" / "anra-common"
    if not dep_dir.exists() and COMMON_CHART_DIR.exists():
        dep_dir.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(str(COMMON_CHART_DIR), str(dep_dir))
    yield
    if dep_dir.exists():
        shutil.rmtree(str(dep_dir))


def _render(*extra_args):
    cmd = ["helm", "template", "anda", str(CHART_DIR), "--namespace", "anda-system"] + list(extra_args)
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    if result.returncode != 0:
        pytest.fail(f"helm template failed: {result.stderr}")
    return result.stdout


def _get_resource(output, kind, name_contains=None):
    docs = list(yaml.safe_load_all(output))
    for d in docs:
        if not d:
            continue
        if d.get("kind") == kind:
            if name_contains is None or name_contains in d["metadata"]["name"]:
                return d
    return None


def _get_all_resources(output, kind):
    docs = list(yaml.safe_load_all(output))
    return [d for d in docs if d and d.get("kind") == kind]


class TestDeployment:
    def test_deployment_exists(self):
        out = _render("--set", "image.repository=test", "--set", "image.tag=v1")
        dep = _get_resource(out, "Deployment")
        assert dep is not None
        assert dep["metadata"]["name"] == "anda"

    def test_agent_role_env(self):
        out = _render("--set", "image.repository=test", "--set", "image.tag=v1")
        dep = _get_resource(out, "Deployment")
        envs = {e["name"]: e["value"] for e in dep["spec"]["template"]["spec"]["containers"][0]["env"] if "value" in e}
        assert envs["AGENT_ROLE"] == "anda"

    def test_agent_config_env(self):
        out = _render("--set", "image.repository=test", "--set", "image.tag=v1")
        dep = _get_resource(out, "Deployment")
        envs = {e["name"]: e["value"] for e in dep["spec"]["template"]["spec"]["containers"][0]["env"] if "value" in e}
        assert envs["AGENT_CONFIG"] == "/app/config/agent-config.yaml"

    def test_bedrock_model_tier_env(self):
        out = _render("--set", "image.repository=test", "--set", "image.tag=v1", "--set", "bedrock.modelTier=fast")
        dep = _get_resource(out, "Deployment")
        envs = {e["name"]: e["value"] for e in dep["spec"]["template"]["spec"]["containers"][0]["env"] if "value" in e}
        assert envs["BEDROCK_MODEL_TIER"] == "fast"

    def test_config_volume_mount(self):
        out = _render("--set", "image.repository=test", "--set", "image.tag=v1")
        dep = _get_resource(out, "Deployment")
        container = dep["spec"]["template"]["spec"]["containers"][0]
        mounts = {m["name"]: m["mountPath"] for m in container["volumeMounts"]}
        assert "config" in mounts
        assert mounts["config"] == "/app/config"

    def test_config_volume_from_configmap(self):
        out = _render("--set", "image.repository=test", "--set", "image.tag=v1")
        dep = _get_resource(out, "Deployment")
        volumes = {v["name"]: v for v in dep["spec"]["template"]["spec"]["volumes"]}
        assert "config" in volumes
        assert "configMap" in volumes["config"]
        assert "anda" in volumes["config"]["configMap"]["name"]

    def test_checksum_annotation(self):
        out = _render("--set", "image.repository=test", "--set", "image.tag=v1")
        dep = _get_resource(out, "Deployment")
        annotations = dep["spec"]["template"]["metadata"].get("annotations", {})
        assert "checksum/config" in annotations

    def test_nf_catalog_mount(self):
        out = _render("--set", "image.repository=test", "--set", "image.tag=v1")
        dep = _get_resource(out, "Deployment")
        container = dep["spec"]["template"]["spec"]["containers"][0]
        mounts = {m["name"]: m["mountPath"] for m in container["volumeMounts"]}
        assert "nf-catalog" in mounts
        assert mounts["nf-catalog"] == "/etc/anda/catalog"


class TestConfigMap:
    def test_configmap_exists(self):
        out = _render("--set", "image.repository=test", "--set", "image.tag=v1")
        cm = _get_resource(out, "ConfigMap", "config")
        assert cm is not None

    def test_configmap_has_agent_config(self):
        out = _render("--set", "image.repository=test", "--set", "image.tag=v1")
        cm = _get_resource(out, "ConfigMap", "config")
        assert "agent-config.yaml" in cm["data"]

    def test_configmap_has_agent_role(self):
        out = _render("--set", "image.repository=test", "--set", "image.tag=v1")
        cm = _get_resource(out, "ConfigMap", "config")
        cfg = yaml.safe_load(cm["data"]["agent-config.yaml"])
        assert cfg["agent_role"] == "anda"

    def test_configmap_bedrock_region(self):
        out = _render("--set", "image.repository=test", "--set", "image.tag=v1", "--set", "bedrock.region=us-east-1")
        cm = _get_resource(out, "ConfigMap", "config")
        cfg = yaml.safe_load(cm["data"]["agent-config.yaml"])
        assert cfg["bedrock"]["region"] == "us-east-1"


class TestArgocdToggle:
    def test_argocd_env_when_enabled(self):
        out = _render("--set", "image.repository=test", "--set", "image.tag=v1", "--set", "argocd.enabled=true")
        dep = _get_resource(out, "Deployment")
        envs = {e["name"]: e["value"] for e in dep["spec"]["template"]["spec"]["containers"][0]["env"] if "value" in e}
        assert envs["ARGOCD_ENABLED"] == "true"

    def test_argocd_env_when_disabled(self):
        out = _render("--set", "image.repository=test", "--set", "image.tag=v1", "--set", "argocd.enabled=false")
        dep = _get_resource(out, "Deployment")
        envs = {e["name"]: e["value"] for e in dep["spec"]["template"]["spec"]["containers"][0]["env"] if "value" in e}
        assert envs["ARGOCD_ENABLED"] == "false"


class TestNetworkPolicy:
    def test_network_policy_rendered_when_enabled(self):
        out = _render("--set", "image.repository=test", "--set", "image.tag=v1", "--set", "networkPolicy.enabled=true")
        np = _get_resource(out, "NetworkPolicy")
        assert np is not None

    def test_network_policy_absent_when_disabled(self):
        out = _render("--set", "image.repository=test", "--set", "image.tag=v1", "--set", "networkPolicy.enabled=false")
        np = _get_resource(out, "NetworkPolicy")
        assert np is None
