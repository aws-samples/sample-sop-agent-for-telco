# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

import logging
import os

import requests
from fastapi import APIRouter

log = logging.getLogger(__name__)
router = APIRouter(tags=["metrics"])


@router.get("/api/metrics")
def get_metrics(measurement: str = "srsran", fields: str = "", range: str = "30m"):
    """Query InfluxDB for time-series metrics."""
    influx_url = os.getenv("INFLUX_URL", "")
    influx_token = os.getenv("INFLUX_TOKEN", "")
    influx_org = os.getenv("INFLUX_ORG", "srs")
    influx_bucket = os.getenv("INFLUX_BUCKET", "srsran")
    if not influx_url:
        return {"series": [], "measurement": measurement}
    field_list = [f.strip() for f in fields.split(",") if f.strip()] if fields else []
    ff = " or ".join(f'r._field == "{f}"' for f in field_list) if field_list else "true"
    flux = (
        f'from(bucket:"{influx_bucket}") |> range(start:-{range}) '
        f'|> filter(fn:(r) => r._measurement == "{measurement}") '
        f"|> filter(fn:(r) => {ff}) "
        f"|> aggregateWindow(every: 5s, fn: last, createEmpty: false)"
    )
    try:
        resp = requests.post(
            f"{influx_url}/api/v2/query?org={influx_org}",
            headers={
                "Authorization": f"Token {influx_token}",
                "Content-Type": "application/vnd.flux",
                "Accept": "application/csv",
            },
            data=flux,
            timeout=15,
        )
        series = {}
        for line in resp.text.strip().split("\r\n"):
            parts = line.split(",")
            if len(parts) >= 8 and parts[0] == "" and parts[6] != "_value":
                ts = parts[5]
                field = parts[7]
                try:
                    val = float(parts[6])
                except (ValueError, IndexError):
                    continue
                if ts not in series:
                    series[ts] = {"time": ts}
                series[ts][field] = val
        return {"series": list(series.values()), "measurement": measurement}
    except Exception as e:
        log.error("Metrics query error: %s", e)
        return {"series": [], "measurement": measurement, "error": str(e)}
