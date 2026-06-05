#!/usr/bin/env python3
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Deploy ANRA agent to AgentCore Runtime via boto3.

This is a Python alternative to the @aws/agentcore npm CLI for environments
where the CLI cannot run (e.g. Amazon Linux 2 with old glibc).

Usage:
    python deploy_via_boto3.py --action create
    python deploy_via_boto3.py --action update
    python deploy_via_boto3.py --action invoke --prompt "What SOPs are available?"
    python deploy_via_boto3.py --action delete
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import boto3

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("agentcore-deploy")

DEFAULT_CONFIG = {
    "agent_name": "anra-agent",
    "region": os.getenv("AWS_REGION", "us-west-2"),
    "python_version": "3.11",
    "memory_mb": 2048,
    "timeout_seconds": 900,
    "idle_timeout_seconds": 3600,
    "max_lifetime_seconds": 28800,
    "execution_role_arn": os.getenv("AGENTCORE_EXECUTION_ROLE_ARN", ""),
    "s3_bucket": os.getenv("AGENTCORE_DEPLOY_BUCKET", ""),
    "subnet_ids": [s for s in os.getenv("AGENTCORE_SUBNETS", "").split(",") if s],
    "security_group_ids": [s for s in os.getenv("AGENTCORE_SECURITY_GROUPS", "").split(",") if s],
    "environment": {
        "BEDROCK_REGION": os.getenv("BEDROCK_REGION", "us-west-2"),
        "AWS_REGION": os.getenv("AWS_REGION", "us-west-2"),
        "ANRA_DEFAULT_MODEL": os.getenv("ANRA_DEFAULT_MODEL", "haiku"),
        "LOG_LEVEL": os.getenv("LOG_LEVEL", "INFO"),
        "SOP_REPO": "/var/task",
    },
}

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEPLOYMENT_DIR = REPO_ROOT / "deployments" / "agentcore"
PACKAGE_DIR = DEPLOYMENT_DIR / "build" / "package"
ZIP_PATH = DEPLOYMENT_DIR / "build" / "deployment.zip"


# ---------------------------------------------------------------------------
# Build steps
# ---------------------------------------------------------------------------


def build_zip(config: dict) -> Path:
    """Install ARM64 wheels and zip the deployment package."""
    log.info("Building deployment package")
    PACKAGE_DIR.parent.mkdir(parents=True, exist_ok=True)
    if PACKAGE_DIR.exists():
        shutil.rmtree(PACKAGE_DIR)
    PACKAGE_DIR.mkdir(parents=True)

    # Install ARM64 wheels for AgentCore Runtime
    pyproject = DEPLOYMENT_DIR / "pyproject.toml"
    log.info("Installing ARM64 wheels via uv")
    subprocess.run(  # noqa: S603 - controlled args
        [
            "uv",
            "pip",
            "install",
            "--python-platform",
            "aarch64-manylinux2014",
            "--python-version",
            config["python_version"],
            "--target",
            str(PACKAGE_DIR),
            "--only-binary=:all:",
            "-r",
            str(pyproject),
        ],
        check=True,
        capture_output=False,
    )

    # Copy main.py + agent/ + sops/ into the package
    shutil.copy(DEPLOYMENT_DIR / "main.py", PACKAGE_DIR / "main.py")
    shutil.copytree(REPO_ROOT / "agent", PACKAGE_DIR / "agent")
    shutil.copytree(REPO_ROOT / "sops", PACKAGE_DIR / "sops")
    if (REPO_ROOT / "alarm-references").exists():
        shutil.copytree(REPO_ROOT / "alarm-references", PACKAGE_DIR / "alarm-references")

    # Create the ZIP
    log.info("Creating ZIP archive")
    if ZIP_PATH.exists():
        ZIP_PATH.unlink()
    with zipfile.ZipFile(ZIP_PATH, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, _, files in os.walk(PACKAGE_DIR):
            for f in files:
                full = Path(root) / f
                rel = full.relative_to(PACKAGE_DIR)
                zf.write(full, rel)

    size_mb = ZIP_PATH.stat().st_size / (1024 * 1024)
    log.info("Package built: %s (%.1f MB)", ZIP_PATH, size_mb)
    if size_mb > 250:
        log.warning("Package exceeds 250 MB AgentCore limit. Consider container deployment.")
    return ZIP_PATH


def upload_to_s3(config: dict, zip_path: Path) -> str:
    """Upload the deployment ZIP to S3 and return the S3 URI."""
    bucket = config["s3_bucket"]
    if not bucket:
        raise ValueError("AGENTCORE_DEPLOY_BUCKET env var must be set")
    key = f"agentcore-deployments/{config['agent_name']}/{zip_path.name}"

    s3 = boto3.client("s3", region_name=config["region"])
    log.info("Uploading to s3://%s/%s", bucket, key)
    s3.upload_file(str(zip_path), bucket, key)
    return f"s3://{bucket}/{key}"


# ---------------------------------------------------------------------------
# AgentCore control plane operations
# ---------------------------------------------------------------------------


def runtime_artifact(s3_uri: str, config: dict) -> dict:
    """Build the agentRuntimeArtifact dict for create/update API calls."""
    return {
        "containerConfiguration": {
            "containerUri": "",  # Direct code deployment uses zipConfiguration
        }
        if False
        else {
            # Direct code deployment path
        },
        "directCodeConfiguration": {
            "s3Configuration": {"s3Uri": s3_uri},
            "handler": "main:app",
            "runtime": f"python{config['python_version']}",
        },
    }


def network_config(config: dict) -> dict:
    """Build the networkConfiguration based on whether VPC is requested."""
    if config["subnet_ids"] and config["security_group_ids"]:
        return {
            "networkMode": "VPC",
            "vpcConfig": {
                "subnetIds": config["subnet_ids"],
                "securityGroupIds": config["security_group_ids"],
            },
        }
    return {"networkMode": "PUBLIC"}


def create_runtime(config: dict, s3_uri: str) -> dict:
    """Create a new AgentCore Runtime."""
    client = boto3.client("bedrock-agentcore-control", region_name=config["region"])
    if not config["execution_role_arn"]:
        raise ValueError("AGENTCORE_EXECUTION_ROLE_ARN env var must be set")

    log.info("Creating agent runtime: %s", config["agent_name"])
    response = client.create_agent_runtime(
        agentRuntimeName=config["agent_name"],
        agentRuntimeArtifact={
            "directCodeConfiguration": {
                "s3Configuration": {"s3Uri": s3_uri},
                "handler": "main:app",
                "runtime": f"python{config['python_version']}",
            },
        },
        networkConfiguration=network_config(config),
        roleArn=config["execution_role_arn"],
        environmentVariables=config["environment"],
        lifecycleConfiguration={
            "idleRuntimeSessionTimeout": config["idle_timeout_seconds"],
            "maxLifetime": config["max_lifetime_seconds"],
        },
    )
    log.info("Created runtime ARN: %s", response["agentRuntimeArn"])
    return response


def update_runtime(config: dict, s3_uri: str) -> dict:
    """Update an existing AgentCore Runtime with new code."""
    client = boto3.client("bedrock-agentcore-control", region_name=config["region"])
    runtime_id = _find_runtime_id(client, config["agent_name"])
    if not runtime_id:
        raise RuntimeError(f"Runtime {config['agent_name']} not found; use --action create first")

    log.info("Updating agent runtime: %s (%s)", config["agent_name"], runtime_id)
    response = client.update_agent_runtime(
        agentRuntimeId=runtime_id,
        agentRuntimeArtifact={
            "directCodeConfiguration": {
                "s3Configuration": {"s3Uri": s3_uri},
                "handler": "main:app",
                "runtime": f"python{config['python_version']}",
            },
        },
        environmentVariables=config["environment"],
        roleArn=config["execution_role_arn"],
    )
    log.info("Updated runtime version: %s", response.get("agentRuntimeVersion"))
    return response


def delete_runtime(config: dict) -> None:
    """Delete the AgentCore Runtime."""
    client = boto3.client("bedrock-agentcore-control", region_name=config["region"])
    runtime_id = _find_runtime_id(client, config["agent_name"])
    if not runtime_id:
        log.warning("Runtime %s not found", config["agent_name"])
        return
    client.delete_agent_runtime(agentRuntimeId=runtime_id)
    log.info("Deleted runtime: %s", runtime_id)


def invoke_runtime(config: dict, payload: dict) -> dict:
    """Invoke the AgentCore Runtime with a payload."""
    client = boto3.client("bedrock-agentcore-runtime", region_name=config["region"])
    log.info("Invoking %s with payload keys: %s", config["agent_name"], list(payload.keys()))

    response = client.invoke_agent_runtime(
        agentRuntimeName=config["agent_name"],
        payload=json.dumps(payload).encode(),
    )
    body = response["payload"].read()
    log.info("Response: %s", body[:500])
    try:
        return json.loads(body)
    except json.JSONDecodeError:
        return {"raw": body.decode()}


def _find_runtime_id(client, name: str) -> str | None:
    paginator = client.get_paginator("list_agent_runtimes")
    for page in paginator.paginate():
        for rt in page.get("agentRuntimes", []):
            if rt["agentRuntimeName"] == name:
                return rt["agentRuntimeId"]
    return None


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--action",
        choices=["build", "create", "update", "invoke", "delete", "describe"],
        required=True,
    )
    parser.add_argument("--prompt", help="Prompt for invoke action")
    parser.add_argument("--payload", help="JSON payload for invoke action")
    parser.add_argument("--profile", help="AWS profile (default: env)")
    args = parser.parse_args()

    if args.profile:
        boto3.setup_default_session(profile_name=args.profile)

    config = DEFAULT_CONFIG

    if args.action == "build":
        build_zip(config)
        return

    if args.action == "create":
        zip_path = build_zip(config)
        s3_uri = upload_to_s3(config, zip_path)
        result = create_runtime(config, s3_uri)
        print(json.dumps(result, default=str, indent=2))
        return

    if args.action == "update":
        zip_path = build_zip(config)
        s3_uri = upload_to_s3(config, zip_path)
        result = update_runtime(config, s3_uri)
        print(json.dumps(result, default=str, indent=2))
        return

    if args.action == "delete":
        delete_runtime(config)
        return

    if args.action == "describe":
        client = boto3.client("bedrock-agentcore-control", region_name=config["region"])
        runtime_id = _find_runtime_id(client, config["agent_name"])
        if not runtime_id:
            print("Runtime not found")
            sys.exit(1)
        info = client.get_agent_runtime(agentRuntimeId=runtime_id)
        print(json.dumps(info, default=str, indent=2))
        return

    if args.action == "invoke":
        if args.payload:
            payload = json.loads(args.payload)
        elif args.prompt:
            payload = {"prompt": args.prompt}
        else:
            print("--prompt or --payload required for invoke", file=sys.stderr)
            sys.exit(1)
        result = invoke_runtime(config, payload)
        print(json.dumps(result, default=str, indent=2))


if __name__ == "__main__":
    main()
