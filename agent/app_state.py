# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""In-memory application state for FastAPI (replace with persistent store at scale)."""

from datetime import datetime, timezone

# ── Collections (mutable singletons; imported by api + monitor) ──
_alarms: list[dict] = []
_active_alarm_names: set = set()
_executions: list[dict] = []
_correlations: list[dict] = []
_pending_approvals: dict[str, dict] = {}


def push_alarm(alarm: dict) -> None:
    """Called by monitor to push new alarms."""
    alarm["timestamp"] = datetime.now(timezone.utc).isoformat()
    _active_alarm_names.add(alarm["name"])
    for i, a in enumerate(_alarms):
        if a["name"] == alarm["name"]:
            _alarms[i] = alarm
            return
    _alarms.append(alarm)
    if len(_alarms) > 200:
        _alarms.pop(0)


def clear_alarms(active_names: set) -> None:
    """Called by monitor each cycle with currently firing alarm names."""
    _active_alarm_names.clear()
    _active_alarm_names.update(active_names)


def push_execution(execution: dict) -> None:
    """Called by monitor/executor to log execution results."""
    execution["timestamp"] = datetime.now(timezone.utc).isoformat()
    _executions.append(execution)


def push_correlation(result: dict) -> None:
    """Called by monitor to store correlation decisions."""
    result["timestamp"] = datetime.now(timezone.utc).isoformat()
    _correlations.append(result)
    if len(_correlations) > 200:
        _correlations.pop(0)


def push_pending_approval(alarm_name: str, sop_path: str, alarm: dict) -> None:
    """Called by monitor when approval_mode=manual."""
    _pending_approvals[alarm_name] = {
        "alarm_name": alarm_name,
        "sop": sop_path,
        "severity": alarm.get("severity", ""),
        "source": alarm.get("source", ""),
        "service_impact": alarm.get("service_impact", ""),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


# ── Live Activity Stream ──
_activity: list[dict] = []


def push_activity(stage: str, message: str, detail: str = "", status: str = "info") -> None:
    """Push structured activity event. Stages: collect|detect|correlate|resolve|enrich|execute|reeval"""
    _activity.append({
        "stage": stage, "message": message, "detail": detail, "status": status,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })
    if len(_activity) > 500:
        _activity.pop(0)
