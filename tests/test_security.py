# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Tests for security controls — command blocklist/allowlist."""
import re
import pytest


# Reproduce the exact patterns from api.py
_BLOCKED_SHELL = re.compile(r'rm\s+-rf\s+/($|\s|[a-z])|mkfs|dd\s+if=|>\s*/dev/sd|chmod\s+-R\s+777\s+/', re.I)
_ALLOWED_KUBECTL = re.compile(r'^(get|describe|logs|top|explain|api-resources|version)\b', re.I)


class TestKubectlAllowlist:
    """Only read-only kubectl commands should be allowed."""

    @pytest.mark.parametrize("cmd", [
        "get pods -n aws-app",
        "get nodes -o wide",
        "describe pod app-service-01",
        "logs app-service-01 --tail=50",
        "top nodes",
        "explain deployment",
        "api-resources",
        "version",
    ])
    def test_allowed_commands(self, cmd):
        assert _ALLOWED_KUBECTL.match(cmd), f"Should allow: {cmd}"

    @pytest.mark.parametrize("cmd", [
        "delete pod app-service-01",
        "delete namespace aws-app",
        "apply -f malicious.yaml",
        "create deployment evil",
        "patch node worker --type merge",
        "edit configmap app-config",
        "drain worker-node",
        "cordon worker-node",
        "replace -f bad.yaml",
    ])
    def test_blocked_commands(self, cmd):
        assert not _ALLOWED_KUBECTL.match(cmd), f"Should block: {cmd}"


class TestShellBlocklist:
    """Destructive shell commands should be blocked."""

    @pytest.mark.parametrize("cmd", [
        "rm -rf /",
        "rm  -rf  /etc",
        "mkfs.ext4 /dev/sda1",
        "dd if=/dev/zero of=/dev/sda",
        "> /dev/sda",
        "chmod -R 777 /",
    ])
    def test_blocked_commands(self, cmd):
        assert _BLOCKED_SHELL.search(cmd), f"Should block: {cmd}"

    @pytest.mark.parametrize("cmd", [
        "ls /tmp",
        "cat /etc/hostname",
        "kubectl get pods",
        "ps aux | grep python",
        "df -h",
    ])
    def test_allowed_commands(self, cmd):
        assert not _BLOCKED_SHELL.search(cmd), f"Should allow: {cmd}"
