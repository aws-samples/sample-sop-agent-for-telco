# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Translate AWS/K8s/Bedrock errors into participant-friendly messages."""

import re

ERROR_PATTERNS = [
    (
        r"AccessDeniedException.*bedrock:InvokeModel",
        "Your AWS account doesn't have Bedrock model access yet.",
        "Visit the Bedrock console (Models → Model access) and enable at least one Claude model.",
    ),
    (
        r"ThrottlingException",
        "Bedrock is rate-limiting your requests.",
        "Wait 30-60 seconds and try again. If it persists, check your account's Bedrock quota.",
    ),
    (
        r"ImagePullBackOff|ErrImagePull",
        "Kubernetes can't pull a container image.",
        "Check (1) ECR repository exists, (2) IAM role has ECR permissions, (3) image tag is correct.",
    ),
    (
        r"OOMKilled",
        "A pod ran out of memory.",
        "Increase memory limits in the deployment OR investigate why the pod is using more memory than expected.",
    ),
    (
        r"connection refused.*8086|influxdb",
        "InfluxDB metrics database is not reachable.",
        "Check the influxdb pod is Running: `kubectl get pods -n srsran | grep influxdb`",
    ),
    (
        r"x509: certificate has expired",
        "A TLS certificate has expired.",
        "Restart the workshop event — certs are regenerated each session.",
    ),
    (
        r"context deadline exceeded",
        "An operation timed out.",
        "The cluster may be slow or overloaded. Wait 30s and retry.",
    ),
]


def translate(raw_error: str) -> dict:
    """Match raw error string against patterns and return friendly translation."""
    for pattern, friendly, action in ERROR_PATTERNS:
        if re.search(pattern, raw_error, re.IGNORECASE):
            return {
                "raw": raw_error[:500],
                "friendly": friendly,
                "action": action,
                "matched": True,
            }
    return {
        "raw": raw_error[:500],
        "friendly": "An unexpected error occurred.",
        "action": "Check the agent logs (/var/log/anra) or report this issue.",
        "matched": False,
    }
