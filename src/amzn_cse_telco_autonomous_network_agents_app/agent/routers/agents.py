# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""FastAPI router for ANO agent status, reasoning feed, and track record."""

from __future__ import annotations

import json
import logging
import os
import shlex
from datetime import datetime, timezone

from fastapi import APIRouter

from amzn_cse_telco_autonomous_network_agents_app.agent.app_state import (
    snapshot_active_alarms,
    snapshot_activity,
    snapshot_executions,
    snapshot_pending_approvals,
)
from amzn_cse_telco_autonomous_network_agents_app.agent.core import deployment_plans

router = APIRouter(tags=["agents"])
logger = logging.getLogger(__name__)


@router.get("/api/agents/reasoning")
def get_agent_reasoning(limit: int = 20):
    """Return the most recent agent reasoning entries from the activity feed.

    Entries are typed as: reasoning | action | decision | escalation
    """
    entries = []
    activity_feed = deployment_plans.merge_activity(snapshot_activity(), deployment_plans.list_plans())
    for activity in activity_feed[-limit:]:
        entry_type = "action"
        stage = activity.get("stage", "")
        message = activity.get("message", "")

        if "correlat" in message.lower() or "detected" in message.lower():
            entry_type = "reasoning"
        elif "sop" in message.lower() or "selected" in message.lower():
            entry_type = "decision"
        elif "escalat" in message.lower() or "failed" in message.lower():
            entry_type = "escalation"

        entries.append(
            {
                "agent": "anda" if message.startswith("Network Change Agent") else _infer_agent(stage),
                "timestamp": activity.get("timestamp", datetime.now(timezone.utc).isoformat()),
                "type": entry_type,
                "message": message,
                "detail": activity.get("detail", ""),
                "status": activity.get("status", ""),
            }
        )

    return {"entries": entries}


@router.get("/api/agents/status")
def get_agent_status():
    """Return the state of each agent (idle/active/thinking/waiting).

    The Assurance Agent's state comes from alarms that are firing now and from
    proposals waiting for approval; the Change Agent's from DeploymentPlans.
    """
    from amzn_cse_telco_autonomous_network_agents_app.agent.core.executor import run_cmd

    active_alarms = [a for a in snapshot_active_alarms() if not a.get("suppressed")]
    pending = snapshot_pending_approvals()
    active_execs = [e for e in snapshot_executions() if e.get("status") == "running"]

    # --- ANRA state ---
    anra_state = "idle"
    anra_detail = "Watching — no active alarms"
    if active_execs:
        anra_state = "active"
        anra_detail = f"Executing SOP: {active_execs[0].get('sop', 'unknown')}"
    elif pending:
        anra_state = "waiting"
        anra_detail = f"Waiting for your approval: {', '.join(sorted(pending))}"
    elif active_alarms:
        anra_state = "thinking"
        anra_detail = f"Correlating {len(active_alarms)} active alarm{'s' if len(active_alarms) != 1 else ''}"

    # --- ANDA state ---
    anda_state = "idle"
    anda_detail = "No active deployments"
    plan = deployment_plans.active_plan(deployment_plans.list_plans())
    if plan:
        anda_state = "active"
        anda_detail = f"Running {plan['sop'] or plan['intent']} for {plan['nf']} — {plan['phase']}"

    # --- ANPA state (from live ProvisioningRequest CRDs) ---
    anpa_state = "idle"
    anpa_detail = "Monitoring infrastructure"
    try:
        result = run_cmd(
            "kubectl get provisioningrequests.provisioning.anpa.aws.io --all-namespaces -o json --field-selector status.phase!=Ready,status.phase!=Failed",
            timeout=3,
        )
        if result.success:
            items = json.loads(result.stdout).get("items", [])
            active_reqs = [r for r in items if r.get("status", {}).get("phase") not in ("Ready", "Failed", None)]
            if active_reqs:
                req = active_reqs[0]
                phase = req.get("status", {}).get("phase", "Pending")
                server = req.get("spec", {}).get("serverName", "unknown")
                anpa_state = "active"
                anpa_detail = f"Provisioning {server} — {phase}"
        # Fallback: count inventory
        if anpa_state == "idle":
            inv_result = run_cmd("kubectl get hardwareinventories --all-namespaces --no-headers 2>/dev/null | wc -l", timeout=3)
            if inv_result.success and inv_result.stdout.strip().isdigit():
                count = int(inv_result.stdout.strip())
                if count > 0:
                    anpa_detail = f"Watching {count} server{'s' if count != 1 else ''} — all healthy"
    except Exception:
        pass

    return {
        "agents": [
            {
                "name": "ANPA",
                "role": "Day 0 — Provisioning",
                "state": anpa_state,
                "detail": anpa_detail,
            },
            {
                "name": "ANDA",
                "role": "Day 1 — Deployment",
                "state": anda_state,
                "detail": anda_detail,
            },
            {
                "name": "ANRA",
                "role": "Day 2 — Remediation",
                "state": anra_state,
                "detail": anra_detail,
            },
        ]
    }


@router.get("/api/anra/incident/current")
def get_current_incident():
    """Return the current active incident (if any) with OODA state."""
    active_execs = [e for e in snapshot_executions() if e.get("status") == "running"]
    active_alarms = snapshot_active_alarms()

    if not active_execs and not active_alarms:
        return {"active": False}

    exec_data = active_execs[0] if active_execs else {}
    steps = exec_data.get("steps", [])

    ooda_state = "OBSERVE"
    if active_alarms and not active_execs:
        ooda_state = "ORIENT"
    elif active_execs:
        all_done = all(s.get("status") == "done" for s in steps)
        ooda_state = "VERIFY" if all_done else "ACT"

    return {
        "active": True,
        "root_cause": {
            "description": exec_data.get("trigger", "Multiple correlated alarms"),
            "causal_chain": [{"event": a.get("name", "unknown"), "time": a.get("fired_at", ""), "type": "alarm"} for a in active_alarms[:5]],
        },
        "sop": {
            "name": exec_data.get("sop", "unknown"),
            "risk": exec_data.get("risk", "LOW"),
            "steps": steps,
            "elapsed_seconds": exec_data.get("elapsed_seconds", 0),
            "estimated_remaining_seconds": exec_data.get("estimated_remaining", 0),
        },
        "success_criteria": exec_data.get("success_criteria", "KPIs return to baseline"),
        "ooda_state": ooda_state,
    }


@router.get("/api/anra/track-record")
def get_track_record(days: int = 7):
    """Remediations the Assurance Agent handed to the Change Agent, from
    DeploymentPlans. Values are None when there is nothing to measure yet."""
    plans = [p for p in (deployment_plans.list_plans() or []) if p["triggered_by"] in ("anra", "")]
    stats = deployment_plans.summary(plans)
    return {
        "incidents_handled": stats["total"],
        "auto_resolved": stats["completed"],
        "completed": stats["completed"],
        "escalated": stats["failed"],
        "in_progress": stats["active"],
        "avg_mttr_auto_seconds": stats["avg_seconds_to_fix"],
        "mttr_minutes": round(stats["avg_seconds_to_fix"] / 60, 1) if stats["avg_seconds_to_fix"] else None,
        "sop_success_rate": stats["success_rate"],
    }


@router.get("/api/anda/active-deployment")
def get_active_deployment(history: int = 10):
    """The DeploymentPlan the Change Agent is running (if any) and recent ones.

    Reads every plan in anda-system and filters in Python: custom resources do
    not support ``--field-selector status.phase``, which is why an earlier
    version always reported "no active deployment".
    """
    plans = deployment_plans.list_plans()
    if plans is None:
        return {"active": False, "history": [], "error": "DeploymentPlans unavailable"}
    plan = deployment_plans.active_plan(plans)
    body: dict = {"active": plan is not None, "history": plans[: max(0, history)]}
    if plan:
        phase = plan["phase"]
        body.update(
            {
                "plan_name": plan["name"],
                "nf": plan["nf"] or "unknown",
                "intent": plan["intent"],
                "alarm": plan["alarm"],
                "sop": plan["sop"],
                "triggered_by": plan["triggered_by"],
                "stage": phase,
                "reasoning": plan["reason"],
                "steps": plan["steps"],
                "stages": [
                    {"name": "Accepted", "status": "done" if phase != "Pending" else "active"},
                    {"name": "Running SOP", "status": "active" if phase == "InProgress" else "pending"},
                    {"name": "Done", "status": "pending"},
                ],
            }
        )
    return body


@router.get("/api/anda/fleet-opinions")
def get_fleet_opinions():
    """Health of each network function, read from its Deployment.

    One row per Deployment in the NF namespace. Health uses the same data as
    the free5gc_nf_unavailable alarm (available vs desired replicas), so the
    dashboard and the alarms agree. A Deployment scaled to 0 stays in the list
    as Down; Jobs and MongoDB are not network functions and are skipped.
    """
    from amzn_cse_telco_autonomous_network_agents_app.agent.core.executor import run_cmd

    namespace = os.getenv("DEFAULT_NF_NAMESPACE", "free5gc")
    result = run_cmd(f"kubectl get deployments -n {shlex.quote(namespace)} -o json", timeout=5)
    if not result.success:
        return {"nfs": [], "error": "NF status unavailable"}
    try:
        items = json.loads(result.stdout or "{}").get("items", [])
    except ValueError:
        return {"nfs": [], "error": "NF status unavailable"}

    nfs = []
    for d in items:
        name = d.get("metadata", {}).get("name", "")
        if not name or "mongodb" in name:
            continue
        desired = d.get("spec", {}).get("replicas", 1)
        available = d.get("status", {}).get("availableReplicas", 0) or 0
        if desired > 0 and available >= desired:
            status = "Running"
        elif available > 0:
            status = "Degraded"
        else:
            status = "Down"
        nfs.append(
            {
                "name": _nf_display_name(name),
                "deployment": name,
                "status": status,
                "detail": f"{available}/{desired} available",
            }
        )
    return {"nfs": sorted(nfs, key=lambda n: n["name"])}


def _nf_display_name(deployment: str) -> str:
    """free5gc-amf-deployment -> AMF, packetrusher-packetrusher -> gNB/UE sim."""
    if deployment.startswith("packetrusher"):
        return "gNB/UE sim"
    return deployment.removeprefix("free5gc-").removesuffix("-deployment").upper()


def _infer_agent(stage: str) -> str:
    """Infer which agent produced an activity entry from its stage field."""
    stage_lower = stage.lower() if stage else ""
    if any(k in stage_lower for k in ("provision", "discover", "inventory", "hardware")):
        return "anpa"
    if any(k in stage_lower for k in ("deploy", "helm", "rollback", "upgrade")):
        return "anda"
    return "anra"
