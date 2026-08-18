# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Alertmanager data source."""

import json
import logging
import os
import shlex
import subprocess

log = logging.getLogger("monitor")

ALERTMANAGER_URL = os.getenv("ALERTMANAGER_URL", "")


def fetch_alertmanager_alerts():
    """Fetch active alerts from Alertmanager."""
    if not ALERTMANAGER_URL:
        return []
    try:
        r = subprocess.run(
            shlex.split(f"curl -s {ALERTMANAGER_URL}/api/v2/alerts"),
            capture_output=True, text=True, timeout=10,
        )
        raw = (r.stdout + r.stderr).strip()
    except Exception:
        return []
    try:
        data = json.loads(raw)
        return [
            {
                "name": a["labels"].get("alertname", "unknown"),
                "severity": a["labels"].get("severity", "warning"),
                "service_impact": a.get("annotations", {}).get("summary", ""),
                "probable_cause": a.get("annotations", {}).get("description", ""),
                "sop": "",
                "source": "alertmanager",
            }
            for a in data
            if a.get("status", {}).get("state") == "active"
            and a["labels"].get("alertname") not in {"Watchdog", "InfoInhibitor"}
        ]
    except (json.JSONDecodeError, TypeError):
        return []
