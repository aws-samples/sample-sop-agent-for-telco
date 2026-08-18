# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

from amzn_cse_telco_autonomous_network_agents_app.agent.app_state import (
    snapshot_alarms_with_active_names,
)
from fastapi import APIRouter

router = APIRouter(tags=["alarms"])


@router.get("/api/alarms")
def get_alarms():
    # Combined snapshot under a single lock so the filter sees a consistent
    # pair — two separate snapshot calls would race a concurrent push_alarm
    # or clear_alarms and produce a stale/mismatched view.
    alarms, active_names = snapshot_alarms_with_active_names()
    active = [a for a in alarms if a["name"] in active_names]
    return {"alarms": active, "count": len(active)}


# Demo trigger buttons — inject a synthetic alarm for each layer
DEMO_ALARMS = {
    "ran": {
        "name": "du_timing_failure", "severity": "critical", "source": "demo-trigger",
        "service_impact": "Cell outage, UE disconnections",
        "probable_cause": "[DEMO] Simulated RAN layer fault — PTP drift causing timing failure",
        "sop": "day2-remediate/ran/remediate-du-timing-failure.md", "value": 999, "threshold": "> 500",
    },
    "core": {
        "name": "nf_crashloop", "severity": "critical", "source": "demo-trigger",
        "service_impact": "Degraded core network",
        "probable_cause": "[DEMO] Simulated Core layer fault — NF health below threshold",
        "sop": "day2-remediate/core/remediate-nf-crashloop.md", "value": 80, "threshold": "< 95",
    },
    "infra": {
        "name": "network_partition", "severity": "critical", "source": "demo-trigger",
        "service_impact": "RAN isolated from core",
        "probable_cause": "[DEMO] Simulated Infra layer fault — network partition detected",
        "sop": "day2-remediate/infra/remediate-network-partition.md", "value": 1, "threshold": "> 0",
    },
    "hardware": {
        "name": "hw_thermal_critical", "severity": "critical", "source": "demo-trigger",
        "service_impact": "Server thermal throttling",
        "probable_cause": "[DEMO] Simulated Hardware layer fault — CPU temperature critical",
        "sop": "", "value": 95, "threshold": "> 85",
    },
    "memory": {
        "name": "os_memory_pressure", "severity": "warning", "source": "demo-trigger",
        "service_impact": "UPF packet processing degraded, potential OOM",
        "probable_cause": "[DEMO] Simulated memory pressure on UPF node",
        "sop": "day2-remediate/infra/remediate-os-memory-pressure.md", "value": 94, "threshold": "> 90",
    },
    "disconnect": {
        "name": "amf_gnb_disconnect", "severity": "critical", "source": "demo-trigger",
        "service_impact": "All UEs disconnected, no NGAP signaling",
        "probable_cause": "[DEMO] Simulated AMF-gNB NGAP N2 connection loss",
        "sop": "day2-remediate/core/remediate-amf-gnb-disconnect.md", "value": 0, "threshold": "< 1",
    },
    "config": {
        "name": "amf_registration_failure", "severity": "critical", "source": "demo-trigger",
        "service_impact": "gNB cannot register — PLMN mismatch",
        "probable_cause": "[DEMO] Simulated config mismatch — wrong PLMN injected",
        "sop": "day2-remediate/ran/remediate-config-mismatch.md", "value": 1, "threshold": "> 0",
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
