# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

from amzn_cse_telco_autonomous_network_agents_app.agent.app_state import push_alarm
from fastapi import APIRouter

router = APIRouter(tags=["webhooks"])


@router.post("/api/alertmanager")
async def receive_alertmanager(payload: dict):
    """Receive alerts from Alertmanager webhook."""
    # Lazy import: monitor pulls in the full ANRA monitoring stack (same
    # pattern as routers/approvals.py).
    from amzn_cse_telco_autonomous_network_agents_app.agent.monitor import alert_from_alertmanager

    count = 0
    for alert in payload.get("alerts", []):
        labels = alert.get("labels", {})
        if alert.get("status") != "firing":
            continue
        if labels.get("alertname", "unknown") in {"Watchdog", "InfoInhibitor"}:
            continue
        push_alarm(alert_from_alertmanager(labels, alert.get("annotations", {}), "alertmanager-webhook"))
        count += 1
    return {"received": count}
