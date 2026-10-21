# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Static and Helm-render validation for the workshop-v3 Free5GC path."""

from __future__ import annotations

import json
import shutil
import subprocess
import tarfile
from pathlib import Path
from subprocess import CompletedProcess

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
MONITORING = ROOT / "configs" / "free5gc-monitoring"
ANRA_VALUES = MONITORING / "anra-values.yaml"
CFN = ROOT / "infra" / "cloudformation" / "vpc-eks-multus.yaml"


def test_cloudformation_uses_restricted_ingress_and_pinned_gtp5g():
    text = CFN.read_text()
    assert "AllowedExternalAccessCidr" in text
    assert "CidrIp: 0.0.0.0/0" not in text
    assert "CidrIp: !Ref VpcCidr" in text
    assert "git clone --branch v0.9.15" in text
    assert "bedrock:InvokeModel" in text
    assert "EndpointPublicAccess: false" in text
    assert "AWSCloudFormationFullAccess" not in text
    assert "BastionAmiIdOverride:" in text
    assert "UseBastionAmiIdOverride:" in text
    assert "ImageId: !If [UseBastionAmiIdOverride, !Ref BastionAmiIdOverride, !Ref LatestAmiId]" in text


def test_ebs_csi_uses_least_privilege_pod_identity():
    text = CFN.read_text()
    assert "AddonName: eks-pod-identity-agent" in text
    assert "AddonVersion: v1.3.10-eksbuild.3" in text
    assert "Service: pods.eks.amazonaws.com" in text
    assert "aws:RequestTag/kubernetes-namespace: kube-system" in text
    assert "aws:RequestTag/kubernetes-service-account: ebs-csi-controller-sa" in text
    assert "PodIdentityAssociations:" in text
    assert "ServiceAccount: ebs-csi-controller-sa" in text
    assert "AmazonEBSCSIDriverPolicy" in text
    worker_role = text.split("  EksNodeRole:", 1)[1].split("  EksEbsCsiPodIdentityRole:", 1)[0]
    assert "AmazonEBSCSIDriverPolicy" not in worker_role


def test_ind321_chart_bundle_is_pinned_and_readable():
    expected = {
        "free5gc-0.0.2.tgz": "free5gc/Chart.yaml",
        "packetrusher-0.0.3.tgz": "packetrusher/Chart.yaml",
    }
    for archive_name, chart_member in expected.items():
        archive = ROOT / "helm-charts" / "free5gc-bundle" / archive_name
        assert archive.exists()
        with tarfile.open(archive, "r:gz") as bundle:
            assert chart_member in bundle.getnames()


def test_monitoring_values_route_alertmanager_to_real_anra_endpoint():
    values = yaml.safe_load((MONITORING / "kube-prometheus-stack-values.yaml").read_text())
    assert values["alertmanager"]["enabled"] is True
    receivers = values["alertmanager"]["config"]["receivers"]
    webhook = receivers[0]["webhook_configs"][0]["url"]
    assert webhook.endswith("/api/alertmanager")
    assert "/api/webhooks/alertmanager" not in webhook
    assert values["grafana"]["admin"]["existingSecret"] == "free5gc-grafana-admin"


def test_free5gc_anra_contract():
    values = yaml.safe_load(ANRA_VALUES.read_text())
    assert values["approval"] == {"mode": "manual", "andaEnabled": "true"}
    assert values["defaults"] == {
        "nfNamespace": "free5gc",
        "nfVendor": "free5gc",
        "ranNamespace": "free5gc",
    }
    assert "free5gc" in values["config"]["nodes"][0]["namespaces"]
    assert "free5gc" in values["config"]["guardrails"]["protected_namespaces"]
    assert values["config"]["alarmReferences"] == ["alarm-references/free5gc.yaml"]
    assert values["selfUpdate"]["enabled"] is False


def test_alert_rules_and_dashboard_are_parseable():
    rules = yaml.safe_load((MONITORING / "free5gc-alert-rules.yaml").read_text())
    assert rules["kind"] == "PrometheusRule"
    configured_rules = {rule["alert"]: rule for group in rules["spec"]["groups"] for rule in group["rules"]}
    names = set(configured_rules)
    assert {
        "free5gc_nf_unavailable",
        "free5gc_metrics_missing",
        "free5gc_registration_unavailable",
        "free5gc_node_not_ready",
    } <= names
    registered_ue_metric = "free5gc_amf_business_ue_gmm_state_count"
    registration_expr = configured_rules["free5gc_registration_unavailable"]["expr"]
    assert registered_ue_metric in registration_expr
    assert 'gmm_state="Registered"' in registration_expr
    assert "free5gc_amf_business_ue_connectivity" not in registration_expr

    anra_values = yaml.safe_load(ANRA_VALUES.read_text())
    configured_alarms = {alarm["name"]: alarm for alarm in anra_values["config"]["alarms"]}
    assert names <= set(configured_alarms)
    assert configured_alarms["free5gc_registration_unavailable"]["field"] == registered_ue_metric

    dashboard = json.loads((MONITORING / "dashboards" / "free5gc-core-overview.json").read_text())
    connected_ues = next(panel for panel in dashboard["panels"] if panel["title"] == "Connected UEs")
    assert registered_ue_metric in connected_ues["targets"][0]["expr"]


def test_configured_alarm_catalog_enriches_runtime_context(tmp_path):
    from amzn_cse_telco_autonomous_network_agents_app.agent.monitor import _merge_alarm_catalogs

    catalog = tmp_path / "catalog.yaml"
    catalog.write_text(
        yaml.safe_dump(
            {
                "alarms": {
                    "free5gc_nf_unavailable": {
                        "probable_cause": "gtp5g or configuration failure",
                        "diagnostics": ["kubectl get pods -n {namespace}"],
                    }
                }
            }
        )
    )
    merged = _merge_alarm_catalogs(
        {"free5gc_nf_unavailable": {"layer": 2, "probable_cause": ""}},
        [str(catalog)],
    )
    assert merged["free5gc_nf_unavailable"]["probable_cause"] == "gtp5g or configuration failure"
    assert merged["free5gc_nf_unavailable"]["diagnostics"] == ["kubectl get pods -n {namespace}"]


def test_vendor_catalog_can_bind_sop_to_alarm(tmp_path):
    """A vendor catalog entry's ``sop`` reaches the merged alarm reference."""
    from amzn_cse_telco_autonomous_network_agents_app.agent.monitor import _merge_alarm_catalogs

    catalog = tmp_path / "catalog.yaml"
    catalog.write_text(
        yaml.safe_dump({"alarms": {"free5gc_nf_unavailable": {"sop": "day2-remediate/core/free5gc-nf-unavailable.md"}}})
    )
    merged = _merge_alarm_catalogs({"free5gc_nf_unavailable": {"layer": 2, "sop": ""}}, [str(catalog)])
    assert merged["free5gc_nf_unavailable"]["sop"] == "day2-remediate/core/free5gc-nf-unavailable.md"

    # config.alarms[].sop still wins over the catalog when both are set.
    merged = _merge_alarm_catalogs({"free5gc_nf_unavailable": {"layer": 2, "sop": "site/override.md"}}, [str(catalog)])
    assert merged["free5gc_nf_unavailable"]["sop"] == "site/override.md"


class TestResolveSopReference:
    """Alertmanager alerts pick up a SOP from the rule annotation or the alarm catalog."""

    REF = {"free5gc_nf_unavailable": {"layer": 2, "sop": "day2-remediate/core/free5gc-nf-unavailable.md"}}

    def test_annotation_wins(self):
        from amzn_cse_telco_autonomous_network_agents_app.agent.monitor import resolve_sop_reference

        sop = resolve_sop_reference(
            "free5gc_nf_unavailable", {"sop": " day2-remediate/core/custom.md "}, alarm_ref=self.REF
        )
        assert sop == "day2-remediate/core/custom.md"

    def test_falls_back_to_alarm_reference(self):
        from amzn_cse_telco_autonomous_network_agents_app.agent.monitor import resolve_sop_reference

        sop = resolve_sop_reference("free5gc_nf_unavailable", {"summary": "x"}, alarm_ref=self.REF)
        assert sop == "day2-remediate/core/free5gc-nf-unavailable.md"

    def test_unknown_alarm_without_annotation_is_empty(self):
        from amzn_cse_telco_autonomous_network_agents_app.agent.monitor import resolve_sop_reference

        assert resolve_sop_reference("something_else", {}, alarm_ref=self.REF) == ""
        assert resolve_sop_reference("something_else", None, alarm_ref={}) == ""

    def test_poll_path_carries_sop(self, monkeypatch):
        from amzn_cse_telco_autonomous_network_agents_app.agent import monitor

        payload = json.dumps(
            [
                {
                    "status": {"state": "active"},
                    "labels": {"alertname": "free5gc_nf_unavailable", "severity": "critical"},
                    "annotations": {"summary": "NF down", "description": "amf unavailable"},
                },
                {
                    "status": {"state": "active"},
                    "labels": {"alertname": "free5gc_pod_restarting", "severity": "warning"},
                    "annotations": {"summary": "restarts", "sop": "day2-remediate/core/free5gc-pod-crashloop.md"},
                },
                {"status": {"state": "active"}, "labels": {"alertname": "Watchdog"}, "annotations": {}},
            ]
        )
        monkeypatch.setattr(monitor, "ALERTMANAGER_URL", "http://alertmanager:9093")
        monkeypatch.setattr(monitor, "_run", lambda cmd, timeout=10: payload)
        monkeypatch.setattr(monitor, "_alarm_ref", self.REF)

        alerts = {a["name"]: a for a in monitor.fetch_alertmanager_alerts()}
        assert set(alerts) == {"free5gc_nf_unavailable", "free5gc_pod_restarting"}
        assert alerts["free5gc_nf_unavailable"]["sop"] == "day2-remediate/core/free5gc-nf-unavailable.md"
        assert alerts["free5gc_pod_restarting"]["sop"] == "day2-remediate/core/free5gc-pod-crashloop.md"

    def test_webhook_carries_sop(self, monkeypatch):
        import asyncio

        from amzn_cse_telco_autonomous_network_agents_app.agent import monitor
        from amzn_cse_telco_autonomous_network_agents_app.agent.routers import webhooks

        pushed = []
        monkeypatch.setattr(webhooks, "push_alarm", pushed.append)
        monkeypatch.setattr(monitor, "_alarm_ref", self.REF)

        result = asyncio.run(
            webhooks.receive_alertmanager(
            {
                "alerts": [
                    {
                        "status": "firing",
                        "labels": {"alertname": "free5gc_nf_unavailable", "severity": "critical"},
                        "annotations": {"summary": "NF down"},
                    },
                    {"status": "resolved", "labels": {"alertname": "free5gc_pod_restarting"}, "annotations": {}},
                ]
            }
            )
        )
        assert result == {"received": 1}
        assert pushed[0]["sop"] == "day2-remediate/core/free5gc-nf-unavailable.md"


def test_anpa_is_disabled_and_not_deployed_by_sop3():
    platform = yaml.safe_load((ROOT / "helm-charts" / "ano-platform" / "values.yaml").read_text())
    assert platform["anpa"]["enabled"] is False
    script = (ROOT / "scripts" / "free5gc" / "04-deploy-monitoring-anra.sh").read_text()
    assert "helm upgrade --install anpa" not in script
    assert "ANPA=skipped" in script


def test_runtime_image_contains_workshop_v3_assets():
    dockerfile = (ROOT / "Dockerfile").read_text()
    assert "COPY configs/free5gc-monitoring /app/configs/free5gc-monitoring" in dockerfile
    assert "COPY scripts /app/scripts" in dockerfile
    assert "COPY helm-charts/free5gc-bundle /app/helm-charts/free5gc-bundle" in dockerfile
    stager = (ROOT / "bin" / "stage-image-context").read_text()
    assert "free5gc-monitoring" in stager
    assert " manifests" not in stager


def test_scripts_do_not_keep_ind321_layout_defaults():
    scripts = list((ROOT / "scripts" / "free5gc").glob("*.sh"))
    assert scripts
    for script in scripts:
        text = script.read_text()
        assert "cfn-templates/vpc-eks-multus.yaml" not in text
        assert 'NAMESPACE="${NAMESPACE:-default}"' not in text
        assert "eks-ind321-lcm" not in text
    sop3 = (ROOT / "scripts" / "free5gc" / "04-deploy-monitoring-anra.sh").read_text()
    assert 'BEDROCK_REGION="${BEDROCK_REGION:-us-west-2}"' in sop3
    assert '--set-string bedrock.region="${BEDROCK_REGION}"' in sop3
    assert "--set infrastructureBootstrap.enabled=false" in sop3


def test_dashboard_health_uses_free5gc_environment(monkeypatch):
    from amzn_cse_telco_autonomous_network_agents_app.agent import cluster

    monkeypatch.setenv("DEFAULT_NF_VENDOR", "free5gc")
    monkeypatch.setenv("DEFAULT_NF_NAMESPACE", "free5gc")

    def fake_kubectl(argv, *, timeout=10):
        del timeout
        if argv[:2] == ["get", "nodes"]:
            return CompletedProcess(argv, 0, stdout="Ready", stderr="")
        if "free5gc" in argv and "free5gc-amf" not in argv:
            return CompletedProcess(
                argv,
                0,
                stdout="free5gc-amf-deployment-abc packetrusher-packetrusher-abc",
                stderr="",
            )
        return CompletedProcess(argv, 0, stdout="", stderr="")

    monkeypatch.setattr(cluster, "kubectl_run", fake_kubectl)
    status = cluster.check_source_status()
    assert status["core"] is True
    assert status["ran"] is True
    assert status["os"] is True


@pytest.mark.skipif(shutil.which("helm") is None, reason="helm not installed")
def test_anra_chart_renders_free5gc_environment_and_alarm_references():
    result = subprocess.run(
        [
            "helm",
            "template",
            "anra",
            str(ROOT / "helm-charts" / "anra"),
            "--namespace",
            "anra-system",
            "--values",
            str(ANRA_VALUES),
            "--set",
            "image.repository=test",
            "--set",
            "image.tag=test",
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    resources = [item for item in yaml.safe_load_all(result.stdout) if item]
    deployment = next(item for item in resources if item.get("kind") == "Deployment")
    env = {item["name"]: item.get("value", "") for item in deployment["spec"]["template"]["spec"]["containers"][0]["env"]}
    assert env["APPROVAL_MODE"] == "manual"
    assert env["DEFAULT_NF_NAMESPACE"] == "free5gc"
    assert env["DEFAULT_NF_VENDOR"] == "free5gc"
    assert env["DEFAULT_RAN_NAMESPACE"] == "free5gc"
    assert env["ALERTMANAGER_URL"].startswith("http://kube-prometheus-stack-alertmanager")
    configmap = next(item for item in resources if item.get("kind") == "ConfigMap" and item["metadata"]["name"] == "anra-config")
    config = yaml.safe_load(configmap["data"]["agent-config.yaml"])
    assert config["alarm_references"] == ["alarm-references/free5gc.yaml"]
    assert config["nodes"][0]["namespaces"] == ["free5gc"]
