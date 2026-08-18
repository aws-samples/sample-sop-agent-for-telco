# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

from amzn_cse_telco_autonomous_network_agents_app.agent.app_state import push_alarm
from fastapi import APIRouter

router = APIRouter(tags=["webhooks"])


@router.post("/api/alertmanager")
async def receive_alertmanager(payload: dict):
    """Receive alerts from Alertmanager webhook."""
    count = 0
    for alert in payload.get("alerts", []):
        labels = alert.get("labels", {})
        annotations = alert.get("annotations", {})
        if alert.get("status") != "firing":
            continue
        name = labels.get("alertname", "unknown")
        if name in {"Watchdog", "InfoInhibitor"}:
            continue
        push_alarm(
            {
                "name": name,
                "severity": labels.get("severity", "warning"),
                "service_impact": annotations.get("summary", ""),
                "probable_cause": annotations.get("description", ""),
                "source": "alertmanager-webhook",
            }
        )
        count += 1
    return {"received": count}
