# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""In-memory application state for FastAPI (replace with persistent store at scale).

These collections are written by the monitor background thread and read by
FastAPI handlers, so every mutation goes through the module-level ``_lock``
and every reader takes a snapshot via the ``snapshot_*`` helpers. Iterating
the bare lists without the snapshot helper risks ``IndexError`` or partial
reads when the writer mutates mid-iteration.
"""
from __future__ import annotations

import threading
from datetime import datetime, timezone

# ── Collections (mutable singletons; imported by api + monitor) ──
_lock = threading.Lock()
_alarms: list[dict] = []
_active_alarm_names: set = set()
_executions: list[dict] = []
_correlations: list[dict] = []
_pending_approvals: dict[str, dict] = {}


def push_alarm(alarm: dict) -> None:
    """Called by monitor to push new alarms."""
    alarm["timestamp"] = datetime.now(timezone.utc).isoformat()
    if not alarm.get("alarmType"):
        try:
            from amzn_cse_telco_autonomous_network_agents_app.agent.standards import classify_alarm
            alarm.update(classify_alarm(alarm.get("name", "")))
        except Exception:
            pass
    with _lock:
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
    with _lock:
        _active_alarm_names.clear()
        _active_alarm_names.update(active_names)


def push_execution(execution: dict) -> None:
    """Called by monitor/executor to log execution results."""
    execution["timestamp"] = datetime.now(timezone.utc).isoformat()
    with _lock:
        _executions.append(execution)


def push_correlation(result: dict) -> None:
    """Called by monitor to store correlation decisions."""
    result["timestamp"] = datetime.now(timezone.utc).isoformat()
    with _lock:
        _correlations.append(result)
        if len(_correlations) > 200:
            _correlations.pop(0)


def push_pending_approval(alarm_name: str, sop_path: str, alarm: dict) -> None:
    """Called by monitor when approval_mode=manual."""
    entry = {
        "alarm_name": alarm_name,
        "sop": sop_path,
        "severity": alarm.get("severity", ""),
        "source": alarm.get("source", ""),
        "service_impact": alarm.get("service_impact", ""),
        "created_at": datetime.now(timezone.utc).isoformat(),
        # NF context for cross-agent handover (DeploymentPlan CR creation)
        "layer": alarm.get("layer", -1),
        "nf_scope": alarm.get("nf_scope", ""),
        "nf_instance": alarm.get("nf_instance", ""),
        "namespace": alarm.get("namespace", ""),
        "node_name": alarm.get("node_name", ""),
        "alarm_id": alarm.get("alarmId", ""),
        "vendor": alarm.get("vendor", ""),
    }
    with _lock:
        _pending_approvals[alarm_name] = entry


def pop_pending_approval(alarm_name: str) -> dict | None:
    """Atomic check-and-remove for the approval router."""
    with _lock:
        return _pending_approvals.pop(alarm_name, None)


# ── Snapshot helpers (call these from FastAPI handlers) ──
# Each takes a shallow copy under the lock so the caller can iterate safely
# without blocking the writer for the duration of the iteration.


def snapshot_alarms() -> list[dict]:
    with _lock:
        return list(_alarms)


def snapshot_active_alarm_names() -> set:
    with _lock:
        return set(_active_alarm_names)


def snapshot_alarms_with_active_names() -> tuple[list[dict], set]:
    """Return (_alarms, _active_alarm_names) snapshotted together under a single
    lock acquisition. Use this when the caller filters one against the other —
    two separate snapshot calls can interleave with a writer (push_alarm /
    clear_alarms) and produce a mismatched pair (a name in active_names whose
    alarm dict is missing from the alarms list, or vice versa).
    """
    with _lock:
        return list(_alarms), set(_active_alarm_names)


def snapshot_executions() -> list[dict]:
    with _lock:
        return list(_executions)


def snapshot_correlations() -> list[dict]:
    with _lock:
        return list(_correlations)


def snapshot_pending_approvals() -> dict[str, dict]:
    with _lock:
        return dict(_pending_approvals)


# ── Live Activity Stream ──
_activity: list[dict] = []


def push_activity(stage: str, message: str, detail: str = "", status: str = "info") -> None:
    """Push structured activity event. Stages: collect|detect|correlate|resolve|enrich|execute|reeval"""
    entry = {
        "stage": stage, "message": message, "detail": detail, "status": status,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    with _lock:
        _activity.append(entry)
        if len(_activity) > 500:
            _activity.pop(0)


def snapshot_activity() -> list[dict]:
    with _lock:
        return list(_activity)
