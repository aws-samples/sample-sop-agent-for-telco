# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Lambda handler for ANRA telco tools — invoked by AgentCore Gateway.

Exposes three tools as MCP-compatible Gateway targets:

- ``kubectl_command`` — run kubectl against an EKS cluster
- ``ssm_command`` — run a command on a managed instance via AWS Systems Manager
- ``influxdb_query`` — query the metrics store

This Lambda is deployed in a VPC so it can reach private resources (EKS API,
InfluxDB endpoints, EC2 instances). The Gateway calls this Lambda with the tool
name in ``context.client_context.custom['bedrockAgentCoreToolName']`` and the
arguments as the event payload.
"""

import json
import logging
import os
import shlex
import subprocess
import time
from typing import Any

import boto3

logger = logging.getLogger()
logger.setLevel(os.getenv("LOG_LEVEL", "INFO"))

# Gateway prepends the target name with "___" delimiter to the tool name.
# e.g. "anra-tools___kubectl_command" → strip to "kubectl_command".
TOOL_NAME_DELIMITER = "___"

# Configuration via environment variables (set by SAM template)
EKS_CLUSTER_NAME = os.getenv("EKS_CLUSTER_NAME", "")
AWS_REGION = os.getenv("AWS_REGION", "us-west-2")
INFLUXDB_URL = os.getenv("INFLUXDB_URL", "")
INFLUXDB_TOKEN_SECRET_ID = os.getenv("INFLUXDB_TOKEN_SECRET_ID", "")
KUBECTL_TIMEOUT = int(os.getenv("KUBECTL_TIMEOUT", "60"))
SSM_TIMEOUT = int(os.getenv("SSM_TIMEOUT", "60"))


def _extract_tool_name(context) -> str:
    """Return the tool name with the target prefix stripped."""
    try:
        original = context.client_context.custom["bedrockAgentCoreToolName"]
    except (AttributeError, KeyError, TypeError):
        return ""
    if TOOL_NAME_DELIMITER in original:
        return original.split(TOOL_NAME_DELIMITER, 1)[1]
    return original


def _ok(body: Any) -> dict:
    """Standard success response."""
    return {"statusCode": 200, "body": json.dumps({"result": body})}


def _err(message: str, code: int = 400) -> dict:
    """Standard error response."""
    return {"statusCode": code, "body": json.dumps({"error": message})}


# ---------------------------------------------------------------------------
# Tool: kubectl_command
# ---------------------------------------------------------------------------


def _ensure_kubeconfig() -> None:
    """Configure kubeconfig for the configured EKS cluster on first call.

    Lambda containers persist between invocations within the same lifecycle, so
    we only need to run aws eks update-kubeconfig once.
    """
    kubeconfig = "/tmp/kubeconfig"
    os.environ["KUBECONFIG"] = kubeconfig
    if os.path.exists(kubeconfig):
        return
    if not EKS_CLUSTER_NAME:
        raise RuntimeError("EKS_CLUSTER_NAME env var must be set for kubectl tool")
    subprocess.run(  # noqa: S603 - controlled args
        [
            "aws",
            "eks",
            "update-kubeconfig",
            "--name",
            EKS_CLUSTER_NAME,
            "--region",
            AWS_REGION,
            "--kubeconfig",
            kubeconfig,
        ],
        check=True,
        capture_output=True,
        timeout=30,
    )


def _kubectl_command(args: dict) -> dict:
    """Run a kubectl command. Args: {'command': 'get pods -n 5gc'}."""
    cmd = args.get("command", "").strip()
    if not cmd:
        return _err("Missing 'command' argument")

    # Reject obvious shell escapes / chaining
    if any(ch in cmd for ch in [";", "&", "|", "`", "$("]):
        return _err("Command contains disallowed shell metacharacters")

    try:
        _ensure_kubeconfig()
    except Exception as e:
        return _err(f"Failed to configure kubeconfig: {e}", 500)

    full = ["kubectl", *shlex.split(cmd)]
    logger.info("Executing kubectl: %s", " ".join(full))
    try:
        result = subprocess.run(  # noqa: S603 - args validated above
            full,
            capture_output=True,
            text=True,
            timeout=KUBECTL_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        return _err(f"kubectl timed out after {KUBECTL_TIMEOUT}s", 504)

    return _ok(
        {
            "stdout": result.stdout,
            "stderr": result.stderr,
            "exit_code": result.returncode,
        }
    )


# ---------------------------------------------------------------------------
# Tool: ssm_command
# ---------------------------------------------------------------------------


def _ssm_command(args: dict) -> dict:
    """Run a shell command on a managed EC2 instance via SSM RunCommand.

    Args: {'instance_id': 'i-...', 'command': 'systemctl status amf'}
    """
    instance_id = args.get("instance_id", "").strip()
    cmd = args.get("command", "").strip()
    if not instance_id or not cmd:
        return _err("Missing required arguments: instance_id, command")

    ssm = boto3.client("ssm", region_name=AWS_REGION)
    try:
        send = ssm.send_command(
            InstanceIds=[instance_id],
            DocumentName="AWS-RunShellScript",
            Parameters={"commands": [cmd]},
            TimeoutSeconds=SSM_TIMEOUT,
        )
    except Exception as e:
        return _err(f"send_command failed: {e}", 500)

    cmd_id = send["Command"]["CommandId"]

    # Poll until the command completes (max SSM_TIMEOUT seconds)
    deadline = time.time() + SSM_TIMEOUT
    while time.time() < deadline:
        time.sleep(2)
        try:
            inv = ssm.get_command_invocation(CommandId=cmd_id, InstanceId=instance_id)
        except ssm.exceptions.InvocationDoesNotExist:
            continue
        if inv["Status"] in ("Pending", "InProgress", "Delayed"):
            continue
        return _ok(
            {
                "status": inv["Status"],
                "stdout": inv.get("StandardOutputContent", ""),
                "stderr": inv.get("StandardErrorContent", ""),
                "exit_code": inv.get("ResponseCode"),
            }
        )
    return _err(f"SSM command timed out after {SSM_TIMEOUT}s", 504)


# ---------------------------------------------------------------------------
# Tool: influxdb_query
# ---------------------------------------------------------------------------


def _influxdb_query(args: dict) -> dict:
    """Query the InfluxDB metrics store with a Flux query.

    Args: {'flux': 'from(bucket:"metrics") |> range(start:-5m) ...'}
    """
    flux = args.get("flux", "").strip()
    if not flux:
        return _err("Missing 'flux' argument")
    if not INFLUXDB_URL:
        return _err("INFLUXDB_URL env var not configured", 500)

    # Lazy import; only needed for this tool
    import requests

    token = ""
    if INFLUXDB_TOKEN_SECRET_ID:
        sm = boto3.client("secretsmanager", region_name=AWS_REGION)
        try:
            token = sm.get_secret_value(SecretId=INFLUXDB_TOKEN_SECRET_ID)["SecretString"]
        except Exception as e:
            return _err(f"Failed to fetch InfluxDB token: {e}", 500)

    url = f"{INFLUXDB_URL.rstrip('/')}/api/v2/query"
    try:
        resp = requests.post(
            url,
            headers={
                "Authorization": f"Token {token}" if token else "",
                "Content-Type": "application/vnd.flux",
                "Accept": "application/csv",
            },
            data=flux,
            timeout=30,
        )
    except requests.RequestException as e:
        return _err(f"InfluxDB request failed: {e}", 502)

    if resp.status_code >= 400:
        return _err(f"InfluxDB returned {resp.status_code}: {resp.text[:200]}", resp.status_code)
    return _ok({"csv": resp.text, "row_count": resp.text.count("\n")})


# ---------------------------------------------------------------------------
# Lambda entry point
# ---------------------------------------------------------------------------

_DISPATCH = {
    "kubectl_command": _kubectl_command,
    "ssm_command": _ssm_command,
    "influxdb_query": _influxdb_query,
}


def lambda_handler(event: dict, context) -> dict:
    """AgentCore Gateway Lambda entry point."""
    tool_name = _extract_tool_name(context)
    logger.info("Tool invocation: %s, args=%s", tool_name, list(event.keys()))

    handler = _DISPATCH.get(tool_name)
    if handler is None:
        return _err(f"Unknown tool: {tool_name}. Available: {list(_DISPATCH)}")

    try:
        return handler(event)
    except Exception as e:
        logger.exception("Tool handler raised")
        return _err(f"Tool handler error: {e}", 500)
