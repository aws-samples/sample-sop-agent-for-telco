# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

from amzn_cse_telco_autonomous_network_agents_app.agent.app_state import (
    snapshot_activity,
    snapshot_correlations,
    snapshot_executions,
)
from fastapi import APIRouter
from amzn_cse_telco_autonomous_network_agents_app.agent.monitoring_stats import build_monitoring_stats_payload

router = APIRouter(tags=["dashboard"])


@router.get("/api/executions")
def get_executions():
    executions = snapshot_executions()
    return {"executions": executions[-50:], "count": len(executions)}


@router.get("/api/events")
def get_events(window: int = 300):
    """Return event timeline for dashboard."""
    from amzn_cse_telco_autonomous_network_agents_app.agent.event_store import get_history

    events = get_history(minutes=max(1, window // 60))
    return {"events": events, "count": len(events), "window_seconds": window}


@router.get("/api/correlations")
def get_correlations():
    """Return recent correlation decisions."""
    correlations = snapshot_correlations()
    return {"correlations": correlations[-50:], "count": len(correlations)}


@router.get("/api/activity")
def get_activity(limit: int = 50):
    """Return live agent activity stream for pipeline animation."""
    return {"activity": snapshot_activity()[-limit:]}


@router.get("/api/monitoring-stats")
def get_monitoring_stats():
    """Return live monitoring coverage stats for dashboard. Always HTTP 200 with stable shape."""
    return build_monitoring_stats_payload()
