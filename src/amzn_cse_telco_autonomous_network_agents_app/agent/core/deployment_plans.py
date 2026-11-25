# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Read DeploymentPlans so the Network Assurance Agent can report what the
Network Change Agent did.

Approved remediations run in the Change Agent (anda) as DeploymentPlan custom
resources in ``anda-system``. The Assurance Agent's own in-memory executions
never see them, so every dashboard view that reports "what was executed"
(history, KPIs, the activity feed, Ask AI) reads them from here.

``kubectl`` is called at most once per ``CACHE_SECONDS``: several dashboard
pages poll every few seconds. Custom resources do not support field selectors
on ``status.phase``, so the full list is read and filtered in Python.
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
from datetime import datetime, timedelta

CACHE_SECONDS = 5
TERMINAL_PHASES = {"Completed", "Failed", "PartiallyFailed", "RolledBack", "Cancelled"}
NAMESPACE = os.getenv("ANDA_NAMESPACE", "anda-system")

_cache_lock = threading.Lock()
_cache: dict = {"at": 0.0, "plans": None}


def _elapsed_seconds(value) -> int | None:
    """'86s' -> 86, '2m5s' -> 125, 86 -> 86."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return int(value)
    match = re.fullmatch(r"\s*(?:(\d+)m)?\s*(?:(\d+(?:\.\d+)?)s)?\s*", str(value))
    if not match or not any(match.groups()):
        return None
    minutes, seconds = match.groups()
    return int(minutes or 0) * 60 + int(float(seconds or 0))


def normalize(item: dict) -> dict:
    """Flatten one DeploymentPlan into the fields the dashboard shows."""
    meta = item.get("metadata", {})
    spec = item.get("spec", {})
    status = item.get("status", {}) or {}
    nfs = spec.get("networkFunctions") or [{}]
    nf = nfs[0].get("name", "") if nfs else ""
    sop_exec = status.get("sopExecution") or {}
    nf_exec = sop_exec.get(nf) or (next(iter(sop_exec.values())) if sop_exec else {})
    sop = spec.get("sopPath", "") or ""
    if sop.startswith("/app/sops/"):
        sop = sop[len("/app/sops/") :]
    phase = status.get("phase") or "Pending"
    created = meta.get("creationTimestamp", "")
    elapsed = _elapsed_seconds(nf_exec.get("elapsed"))
    finished = ""
    if phase in TERMINAL_PHASES and created and elapsed is not None:
        try:
            start = datetime.fromisoformat(created.replace("Z", "+00:00"))
            finished = (start + timedelta(seconds=elapsed)).isoformat()
        except ValueError:
            finished = ""
    return {
        "name": meta.get("name", ""),
        "alarm": (meta.get("labels") or {}).get("alarm", ""),
        "nf": nf,
        "intent": spec.get("intent", ""),
        "sop": sop,
        "reason": spec.get("reason", ""),
        "triggered_by": spec.get("triggeredBy", ""),
        "phase": phase,
        "message": status.get("message", ""),
        "steps": nf_exec.get("stepsExecuted"),
        "elapsed_seconds": elapsed,
        "created": created,
        "finished": finished,
        "active": phase not in TERMINAL_PHASES,
    }


def list_plans(refresh: bool = False) -> list[dict] | None:
    """All DeploymentPlans, newest first. None if the cluster can't be read."""
    with _cache_lock:
        if not refresh and _cache["plans"] is not None and time.time() - _cache["at"] < CACHE_SECONDS:
            return list(_cache["plans"])
    from amzn_cse_telco_autonomous_network_agents_app.agent.core.executor import run_cmd

    result = run_cmd(f"kubectl get deploymentplans.deployment.anda.aws.io -n {NAMESPACE} -o json", timeout=5)
    if not result.success:
        return None
    try:
        items = json.loads(result.stdout or "{}").get("items", [])
    except (json.JSONDecodeError, AttributeError):
        return None
    plans = sorted((normalize(i) for i in items), key=lambda p: p["created"], reverse=True)
    with _cache_lock:
        _cache.update(at=time.time(), plans=plans)
    return list(plans)


def active_plan(plans: list[dict] | None) -> dict | None:
    for plan in plans or []:
        if plan["active"]:
            return plan
    return None


def as_executions(plans: list[dict] | None) -> list[dict]:
    """Plans in the shape of ``state._executions`` entries, oldest first."""
    result_for = {"Completed": "completed", "Failed": "failed", "PartiallyFailed": "failed"}
    out = []
    for plan in reversed(plans or []):
        out.append(
            {
                "alarm": plan["alarm"] or plan["nf"],
                "sop": plan["sop"],
                "result": result_for.get(plan["phase"], "running" if plan["active"] else plan["phase"].lower()),
                "status": plan["phase"],
                "plan": plan["name"],
                "executed_by": "Network Change Agent",
                "elapsed_seconds": plan["elapsed_seconds"],
                "steps": plan["steps"],
                "timestamp": plan["finished"] or plan["created"],
            }
        )
    return out


def as_activity(plans: list[dict] | None) -> list[dict]:
    """Activity-feed entries for plan outcomes (the start is logged at approval)."""
    out = []
    for plan in plans or []:
        if plan["active"] or not plan["finished"]:
            continue
        ok = plan["phase"] == "Completed"
        steps = f", {plan['steps']} steps" if plan["steps"] else ""
        out.append(
            {
                "stage": "execute",
                "message": "Network Change Agent: plan %s %s in %ss%s" % (plan["name"], plan["phase"], plan["elapsed_seconds"], steps),
                "detail": plan["sop"],
                "status": "success" if ok else "error",
                "timestamp": plan["finished"],
            }
        )
    return out


def merge_activity(activity: list[dict], plans: list[dict] | None) -> list[dict]:
    """Local activity plus plan outcomes, ordered by time (oldest first)."""
    merged = list(activity) + as_activity(plans)
    return sorted(merged, key=lambda e: e.get("timestamp", ""))


def summary(plans: list[dict] | None) -> dict:
    """Counts for the track record and KPI tiles. Times are approval to finish."""
    plans = plans or []
    finished = [p for p in plans if not p["active"]]
    completed = [p for p in finished if p["phase"] == "Completed"]
    times = [p["elapsed_seconds"] for p in completed if p["elapsed_seconds"] is not None]
    return {
        "total": len(plans),
        "active": len(plans) - len(finished),
        "completed": len(completed),
        "failed": len(finished) - len(completed),
        "success_rate": round(len(completed) / len(finished), 2) if finished else None,
        "avg_seconds_to_fix": int(sum(times) / len(times)) if times else None,
    }


def _reset_cache_for_tests() -> None:
    with _cache_lock:
        _cache.update(at=0.0, plans=None)
