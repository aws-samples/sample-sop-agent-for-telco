# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

import json
import os
from pathlib import Path

from fastapi import APIRouter
from pydantic import BaseModel

from amzn_cse_telco_autonomous_network_agents_app.agent.app_state import (
    snapshot_active_alarms,
    snapshot_correlations,
    snapshot_executions,
    snapshot_pending_approvals,
)
from amzn_cse_telco_autonomous_network_agents_app.agent.core import deployment_plans
from amzn_cse_telco_autonomous_network_agents_app.agent.live_topology import build_live_topology
from amzn_cse_telco_autonomous_network_agents_app.agent.monitoring_stats import build_monitoring_stats_payload

router = APIRouter(tags=["chat"])


class ChatRequest(BaseModel):
    message: str


@router.post("/api/chat")
async def chat(req: ChatRequest):
    """Ask AI: answer questions about alarms, approvals, changes and SOPs from
    the Network Assurance Agent's live state (see ``build_chat_context``).

    With CHAT_SWARM=1, cross-domain queries go to the ANO swarm instead.
    """
    # The multi-agent swarm (ANPA + ANDA + ANRA) is opt-in: in the workshop ANPA
    # is not deployed, and the swarm's agents do not see this pod's live state,
    # so a "what caused..." question would be answered without the incident data.
    try:
        from amzn_cse_telco_autonomous_network_agents_app.agent.core.swarm import is_complex_query

        if os.getenv("CHAT_SWARM", "0") == "1" and is_complex_query(req.message):
            return await _handle_swarm_query(req.message)
    except Exception:
        # Fall through to single-agent if swarm fails
        pass

    # Single-agent path (existing behavior)
    try:
        from strands import Agent

        from amzn_cse_telco_autonomous_network_agents_app.agent.core.model_resolver import (
            build_model,
        )
        from amzn_cse_telco_autonomous_network_agents_app.agent.framework.enums import (
            ModelTier,
        )

        model = build_model(ModelTier.FAST)

        agent = Agent(model=model, system_prompt=build_chat_context())
        result = agent(req.message)
        return {"response": str(result)}
    except Exception as e:
        return {"response": f"Sorry, I couldn't process that: {str(e)[:200]}"}


async def _handle_swarm_query(message: str) -> dict:
    """Route a complex query through the ANO multi-agent swarm."""
    import asyncio
    from concurrent.futures import ThreadPoolExecutor

    try:
        from amzn_cse_telco_autonomous_network_agents_app.agent.core.swarm import create_ano_swarm

        swarm = create_ano_swarm()

        # Run swarm in thread pool to avoid blocking the async event loop
        loop = asyncio.get_event_loop()
        with ThreadPoolExecutor(max_workers=1) as pool:
            result = await loop.run_in_executor(pool, swarm, message)

        return {
            "response": str(result),
            "mode": "swarm",
        }
    except Exception as e:
        return {"response": f"Swarm failed, falling back: {str(e)[:200]}", "mode": "error"}


def _sop_dir() -> Path:
    """SOPs ship in the image under ``$SOP_REPO/sops`` (``/app/sops``)."""
    repo = os.getenv("SOP_REPO")
    if repo:
        return Path(repo) / "sops"
    return Path(__file__).resolve().parents[4] / "sops"


def _list_sops() -> list[str]:
    root = _sop_dir()
    try:
        return sorted(str(f.relative_to(root)) for f in root.rglob("*.md") if f.stem != "TEMPLATE" and "archive" not in f.relative_to(root).parts)
    except OSError:
        return []


def build_chat_context() -> str:
    """System prompt for Ask AI, built only from live state.

    Alarms are the ones firing now (the alarm store also keeps history);
    executions include the DeploymentPlans the Change Agent ran after approval;
    each correlation names the alarm it was about.
    """
    alarms = snapshot_active_alarms()
    active = [{"name": a["name"], "severity": a.get("severity", "")} for a in alarms if not a.get("suppressed")]
    suppressed = [{"name": a["name"], "symptom_of": a.get("root_cause", "")} for a in alarms if a.get("suppressed")]
    pending = [{"alarm": name, "sop": (p.get("sop") or "").replace("/app/sops/", "")} for name, p in snapshot_pending_approvals().items()]
    plans = deployment_plans.list_plans() or []
    plan_rows = [
        {
            "plan": p["name"],
            "alarm": p["alarm"],
            "sop": p["sop"],
            "phase": p["phase"],
            "created": p["created"],
            "seconds": p["elapsed_seconds"],
            "steps": p["steps"],
        }
        for p in plans[:5]
    ]
    local_execs = [{"alarm": e.get("alarm"), "result": e.get("result")} for e in snapshot_executions()[-5:]]
    correlations = [
        {
            "alarm": c.get("alarm", ""),
            "decision": c.get("action"),
            "root_cause": c.get("root_cause"),
            "time": c.get("timestamp", ""),
        }
        for c in snapshot_correlations()[-8:]
    ]
    try:
        nf_pods = build_live_topology().get("summary", {}).get("nf_count", 0)
    except Exception:
        nf_pods = "unknown"
    try:
        rules = build_monitoring_stats_payload().get("tier1_rules", "unknown")
    except Exception:
        rules = "unknown"
    sops = _list_sops()
    approval_mode = os.getenv("APPROVAL_MODE", "auto")

    def dump(value) -> str:
        return json.dumps(value, default=str)

    return f"""You are the Network Assurance Agent for a Free5GC 5G core with a PacketRusher gNB/UE simulator.
You watch alarms, correlate them, and propose reviewed SOPs. Approval mode is "{approval_mode}": in manual
mode nothing runs until a person approves; approved SOPs run in the Network Change Agent as DeploymentPlans.
Answer concisely using ONLY the data below. If a list is empty, say so plainly. Do not invent alarms, SOPs,
executions or numbers.

ALARMS FIRING NOW ({len(active)}): {dump(active)}
SUPPRESSED AS SYMPTOMS ({len(suppressed)}): {dump(suppressed)}
PENDING APPROVALS ({len(pending)}): {dump(pending)}
CHANGES RUN BY THE NETWORK CHANGE AGENT (newest first, seconds = approval to finish): {dump(plan_rows)}
SOPs RUN BY THIS AGENT ITSELF: {dump(local_execs)}
RECENT CORRELATION DECISIONS (decision "suppress" means the alarm was treated as a symptom of root_cause;
"execute" means it was treated as a root cause and an SOP was proposed): {dump(correlations)}
NETWORK: {nf_pods} Free5GC/PacketRusher pods tracked; {rules} Prometheus alert rules.
SOPs AVAILABLE ({len(sops)}): {", ".join(sops)}
"""
