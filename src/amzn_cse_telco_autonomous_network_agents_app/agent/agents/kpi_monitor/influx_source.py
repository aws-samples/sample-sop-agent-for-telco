# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""InfluxDB data source — queries time-series metrics."""

import logging
import os

log = logging.getLogger("monitor")

INFLUX_URL = os.getenv("INFLUX_URL", "")
INFLUX_TOKEN = os.getenv("INFLUX_TOKEN", "")
INFLUX_ORG = os.getenv("INFLUX_ORG", "srs")
INFLUX_BUCKET = os.getenv("INFLUX_BUCKET", "srsran")

# Cache last results for anomaly detection baseline
_last_influx_results: dict = {}


def query_influx(measurement, fields):
    """Query InfluxDB for latest values of specified fields."""
    if not INFLUX_URL:
        return {}
    import requests

    ff = " or ".join(f'r._field == "{f}"' for f in fields)
    flux = (
        f'from(bucket:"{INFLUX_BUCKET}") |> range(start:-30s) '
        f'|> filter(fn:(r) => r._measurement == "{measurement}") '
        f'|> filter(fn:(r) => {ff}) |> last()'
    )
    try:
        resp = requests.post(
            f"{INFLUX_URL}/api/v2/query?org={INFLUX_ORG}",
            headers={
                "Authorization": f"Token {INFLUX_TOKEN}",
                "Content-Type": "application/vnd.flux",
                "Accept": "application/csv",
            },
            data=flux,
            timeout=10,
        )
        vals = {}
        for line in resp.text.strip().split("\r\n"):
            parts = line.split(",")
            if len(parts) >= 8 and parts[0] == "" and parts[6] != "_value":
                try:
                    vals[parts[7]] = float(parts[6])
                except (ValueError, IndexError):
                    pass
        _last_influx_results[measurement] = vals
        return vals
    except Exception as e:
        log.error(f"InfluxDB query error: {e}")
        return {}


def query_influx_all(measurement="srsran"):
    """Query ALL latest field values from a measurement."""
    if not INFLUX_URL:
        return {}
    import requests

    flux = (
        f'from(bucket:"{INFLUX_BUCKET}") |> range(start:-30s) '
        f'|> filter(fn:(r) => r._measurement == "{measurement}") |> last()'
    )
    try:
        resp = requests.post(
            f"{INFLUX_URL}/api/v2/query?org={INFLUX_ORG}",
            headers={
                "Authorization": f"Token {INFLUX_TOKEN}",
                "Content-Type": "application/vnd.flux",
                "Accept": "application/csv",
            },
            data=flux,
            timeout=10,
        )
        vals = {}
        for line in resp.text.strip().split("\r\n"):
            parts = line.split(",")
            if len(parts) >= 8 and parts[0] == "" and parts[6] != "_value":
                try:
                    vals[parts[7]] = float(parts[6])
                except (ValueError, IndexError):
                    pass
        return vals
    except Exception:
        return {}
