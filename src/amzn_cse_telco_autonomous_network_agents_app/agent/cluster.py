# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Thin kubectl subprocess wrapper — centralize timeouts and argv-style calls."""
from __future__ import annotations

import logging
import subprocess
from subprocess import CompletedProcess

log = logging.getLogger(__name__)


def kubectl_run(argv: list[str], *, timeout: int = 10) -> CompletedProcess[str]:
    """Run kubectl with fixed argv list (no shell)."""
    return subprocess.run(
        ["kubectl", *argv],
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def check_source_status() -> dict[str, bool]:
    """Check workload pod status for each dashboard monitoring source."""
    sources: dict[str, bool] = {}
    checks = [
        ("ran", "srsran", "srsran-gnb"),
        ("core", "open5gs", "open5gs-amf"),
        ("hardware", "anra", "telegraf-hw"),
        ("os", "", ""),
    ]
    for name, ns, prefix in checks:
        if name == "os":
            try:
                r = kubectl_run(
                    ["get", "nodes", "-o", "jsonpath={.items[*].status.conditions[-1:].type}"],
                    timeout=5,
                )
                sources[name] = "Ready" in r.stdout
            except Exception:
                sources[name] = False
        else:
            try:
                r = kubectl_run(
                    [
                        "get",
                        "pods",
                        "-n",
                        ns,
                        "--field-selector=status.phase=Running",
                        "-o",
                        "jsonpath={.items[*].metadata.name}",
                    ],
                    timeout=5,
                )
                sources[name] = any(p.startswith(prefix) for p in r.stdout.split())
            except Exception:
                sources[name] = False
    return sources
