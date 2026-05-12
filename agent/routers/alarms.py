# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

from app_state import _active_alarm_names, _alarms
from fastapi import APIRouter

router = APIRouter(tags=["alarms"])


@router.get("/api/alarms")
def get_alarms():
    active = [a for a in _alarms if a["name"] in _active_alarm_names]
    return {"alarms": active, "count": len(active)}


# Demo trigger buttons — inject a synthetic alarm for each layer
DEMO_ALARMS = {
    "ran": {
        "name": "amf_gnb_disconnect", "severity": "critical", "source": "demo-trigger",
        "service_impact": "All UEs lose service, gNB disconnected from core",
        "probable_cause": "[DEMO] AMF pod killed — gNB lost SCTP connection",
        "sop": "workshop-remediate/remediate-amf-gnb-disconnect.md", "value": 0, "threshold": "> 0",
    },
    "core": {
        "name": "nf_crashloop", "severity": "critical", "source": "demo-trigger",
        "service_impact": "Degraded core network, NF pod in CrashLoopBackOff",
        "probable_cause": "[DEMO] Core NF pod crashed — service degraded below 95%",
        "sop": "workshop-remediate/remediate-nf-crashloop.md", "value": 80, "threshold": "< 95",
    },
    "infra": {
        "name": "upf_pfcp_loss", "severity": "critical", "source": "demo-trigger",
        "service_impact": "No new PDU sessions, data plane disrupted",
        "probable_cause": "[DEMO] UPF pod killed — PFCP association lost with SMF",
        "sop": "workshop-remediate/remediate-upf-pfcp-loss.md", "value": 0, "threshold": "> 0",
    },
    "hardware": {
        "name": "resource_exhaustion", "severity": "critical", "source": "demo-trigger",
        "service_impact": "NF pods evicted due to resource pressure",
        "probable_cause": "[DEMO] Resource hog consuming CPU/memory — NFs starved",
        "sop": "workshop-remediate/remediate-nf-crashloop.md", "value": 95, "threshold": "> 85",
    },
}

# Injection queue — monitor loop drains this into its alerts[] each cycle
_injected_queue: list = []


@router.post("/api/alarms/trigger/{layer}")
def trigger_demo_alarm(layer: str):
    """Inject a demo alarm into the monitor's detection pipeline."""
    if layer not in DEMO_ALARMS:
        return {"error": f"Unknown layer: {layer}. Use: {list(DEMO_ALARMS.keys())}"}
    alarm = {**DEMO_ALARMS[layer]}
    _injected_queue.append(alarm)
    return {"triggered": alarm["name"], "layer": layer, "message": "Queued — monitor will process on next cycle (≤30s)"}
