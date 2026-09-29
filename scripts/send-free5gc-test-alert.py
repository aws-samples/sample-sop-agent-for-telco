#!/usr/bin/env python3
"""Send a non-remediating workshop test alert through Alertmanager."""

from __future__ import annotations

import argparse
import json
import subprocess
import time
import urllib.request
from datetime import datetime, timedelta, timezone


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--namespace", default="monitoring")
    parser.add_argument("--service", default="kube-prometheus-stack-alertmanager")
    parser.add_argument("--local-port", type=int, default=19093)
    parser.add_argument("--alert-name", default="Free5GCWorkshopPipelineTest")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    process = subprocess.Popen(
        [
            "kubectl",
            "port-forward",
            "-n",
            args.namespace,
            f"service/{args.service}",
            f"{args.local_port}:9093",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        deadline = time.monotonic() + 20
        ready_url = f"http://127.0.0.1:{args.local_port}/-/ready"
        while time.monotonic() < deadline:
            if process.poll() is not None:
                error = process.stderr.read() if process.stderr else ""
                raise RuntimeError(f"kubectl port-forward failed: {error}")
            try:
                with urllib.request.urlopen(ready_url, timeout=1) as response:
                    if response.status == 200:
                        break
            except OSError:
                time.sleep(0.5)
        else:
            raise TimeoutError("Alertmanager port-forward did not become ready")

        now = datetime.now(timezone.utc)
        payload = [
            {
                "labels": {
                    "alertname": args.alert_name,
                    "severity": "info",
                    "source": "workshop-v3-pipeline-test",
                },
                "annotations": {"summary": "Non-mutating workshop-v3 Alertmanager to ANRA test"},
                "startsAt": now.isoformat(),
                "endsAt": (now + timedelta(minutes=2)).isoformat(),
            }
        ]
        request = urllib.request.Request(
            f"http://127.0.0.1:{args.local_port}/api/v2/alerts",
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=5) as response:
            if response.status not in (200, 202):
                raise RuntimeError(f"Alertmanager returned HTTP {response.status}")
        print(f"Sent {args.alert_name}; it has no remediation SOP mapping.")
        return 0
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()


if __name__ == "__main__":
    raise SystemExit(main())
