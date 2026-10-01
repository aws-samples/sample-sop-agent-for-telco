# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Regression tests for Workshop Studio's preconfigured Kubernetes context."""

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOP1 = ROOT / "sops" / "day1-deploy" / "deploy-free5gc-core.sop.md"
SCRIPT_DIR = ROOT / "scripts" / "free5gc"


def test_sop1_uses_current_context_without_infrastructure_parameters():
    text = SOP1.read_text()

    assert "**namespace** (optional" in text
    assert "**stack_name**" not in text
    assert "**aws_region**" not in text
    assert "kubectl config current-context" in text
    assert "aws eks update-kubeconfig" in text  # Explicitly prohibited by the SOP.
    assert "MUST NOT run `aws eks update-kubeconfig`" in text


def test_sop1_scripts_never_replace_the_current_context():
    scripts = [
        SCRIPT_DIR / "02-configure-cluster.sh",
        SCRIPT_DIR / "03-deploy-workloads.sh",
        SCRIPT_DIR / "fix-subscriber-slice.sh",
    ]

    for script in scripts:
        text = script.read_text()
        assert "kubectl config current-context" in text, script
        assert "aws eks update-kubeconfig" not in text, script
        assert "STACK_NAME" not in text, script
        assert "CLUSTER_NAME" not in text, script


def test_participant_cluster_configuration_does_not_repair_hosts_through_aws():
    text = (SCRIPT_DIR / "02-configure-cluster.sh").read_text()

    assert "aws ec2" not in text
    assert "aws ssm" not in text
    assert "send-command" not in text
    assert "kubectl get --raw=/readyz" in text
    assert "rollout status daemonset/kube-multus-ds" in text
    assert "rollout status deployment/metrics-server" in text


def test_sop3_uses_current_context_without_infrastructure_parameters():
    sop = ROOT / "sops" / "day1-deploy" / "deploy-free5gc-monitoring-anra.sop.md"
    text = sop.read_text()

    assert "**stack_name**" not in text
    assert "**aws_region**" not in text
    assert "kubectl config current-context" in text
    assert "MUST NOT run `aws eks update-kubeconfig`" in text
    assert "current Git commit short SHA" in text


def test_sop3_installer_derives_metadata_without_switching_contexts():
    text = (SCRIPT_DIR / "04-deploy-monitoring-anra.sh").read_text()

    assert "kubectl config current-context" in text
    assert "kubectl config view --minify" in text
    assert "KUBE_CLUSTER_REFERENCE" in text
    assert "aws eks update-kubeconfig" not in text
    assert "STACK_NAME" not in text
    assert 'AGENT_IMAGE_TAG="${AGENT_IMAGE_TAG:-$(git -C' in text
    assert 'AGENT_IMAGE_TAG}" = "latest"' in text
    assert '--set-string config.cluster.name="${CLUSTER_NAME}"' in text
    assert '--set-string config.cluster.region="${AWS_DEFAULT_REGION}"' in text
