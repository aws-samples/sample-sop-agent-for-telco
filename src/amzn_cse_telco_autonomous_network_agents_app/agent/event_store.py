# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Event timeline: in-memory ring buffer + InfluxDB persistence.

Customers: swap deque → Amazon Timestream for multi-site, durable event storage.
"""

from __future__ import annotations
import logging
import os
import subprocess
import time
from collections import deque

log = logging.getLogger("monitor")

INFLUX_URL = os.getenv("INFLUX_URL", "")
INFLUX_TOKEN = os.getenv("INFLUX_TOKEN", "")
INFLUX_ORG = os.getenv("INFLUX_ORG", "srs")
INFLUX_BUCKET = os.getenv("INFLUX_BUCKET", "srsran")
BUFFER_TTL = int(os.getenv("EVENT_BUFFER_TTL", "600"))

_buffer: deque = deque(maxlen=2000)


def record(alarm: dict, alarm_ref: dict = None) -> None:
    """Record alarm to buffer + InfluxDB. Never raises."""
    try:
        ref = (alarm_ref or {}).get(alarm.get("name", ""), {})
        event = {
            "ts": time.time(),
            "name": alarm.get("name", "unknown"),
            "severity": alarm.get("severity", "warning"),
            "layer": ref.get("layer", -1),
            "source": alarm.get("source", ""),
            "node": alarm.get("node_name", ""),
            "nf": alarm.get("nf_instance", ""),
            "value": alarm.get("value", 0),
        }
        _buffer.append(event)
        _write_influx(event)
    except Exception as e:
        log.debug(f"Event record failed: {e}")


def get_recent(window: int = 60) -> list[dict]:
    """Return events within window (seconds) from buffer, time-ascending."""
    _prune()
    cutoff = time.time() - window
    return [e for e in _buffer if e["ts"] >= cutoff]


def get_history(minutes: int = 60) -> list[dict]:
    """Query InfluxDB for dashboard. Falls back to buffer on failure."""
    if not INFLUX_URL:
        return list(_buffer)
    try:
        flux = (
            f'from(bucket:"{INFLUX_BUCKET}") |> range(start:-{minutes}m) '
            f'|> filter(fn:(r) => r._measurement == "anra_events") |> last()'
        )
        r = subprocess.run(
            [
                "curl",
                "-s",
                "-H",
                f"Authorization: Token {INFLUX_TOKEN}",
                "-H",
                "Content-Type: application/vnd.flux",
                "-d",
                flux,
                f"{INFLUX_URL}/api/v2/query?org={INFLUX_ORG}",
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if r.returncode == 0 and r.stdout.strip():
            return list(_buffer)  # TODO: parse InfluxDB CSV response for production use
    except Exception:
        pass
    return list(_buffer)


def _write_influx(event: dict) -> None:
    """POST line protocol to InfluxDB. Silent on failure."""
    if not INFLUX_URL:
        return
    try:
        tags = f"layer={event['layer']},severity={event['severity']},source={event['source']}"
        fields = (
            f'alarm_name="{event["name"]}",value={event.get("value", 0)},'
            f'node="{event.get("node", "")}",nf="{event.get("nf", "")}"'
        )
        line = f"anra_events,{tags} {fields} {int(event['ts'] * 1e9)}"
        subprocess.run(
            [
                "curl",
                "-s",
                "-o",
                "/dev/null",
                "-H",
                f"Authorization: Token {INFLUX_TOKEN}",
                "--data-raw",
                line,
                f"{INFLUX_URL}/api/v2/write?org={INFLUX_ORG}&bucket={INFLUX_BUCKET}",
            ],
            capture_output=True,
            timeout=5,
        )
    except Exception as e:
        log.debug(f"InfluxDB event write failed: {e}")


def _prune() -> None:
    """Remove entries older than BUFFER_TTL."""
    cutoff = time.time() - BUFFER_TTL
    while _buffer and _buffer[0]["ts"] < cutoff:
        _buffer.popleft()
