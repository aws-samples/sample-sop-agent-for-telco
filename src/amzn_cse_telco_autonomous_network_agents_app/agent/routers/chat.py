# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

import json
from pathlib import Path

from amzn_cse_telco_autonomous_network_agents_app.agent.app_state import (
    snapshot_alarms,
    snapshot_correlations,
    snapshot_executions,
    snapshot_pending_approvals,
)
from fastapi import APIRouter
from amzn_cse_telco_autonomous_network_agents_app.agent.live_topology import build_live_topology
from amzn_cse_telco_autonomous_network_agents_app.agent.monitoring_stats import build_monitoring_stats_payload
from pydantic import BaseModel

router = APIRouter(tags=["chat"])


class ChatRequest(BaseModel):
    message: str


@router.post("/api/chat")
async def chat(req: ChatRequest):
    """Chat with ANRA agent — ask about alarms, nodes, SOPs.

    Routes complex cross-domain queries to the ANO Swarm (ANPA + ANDA + ANRA).
    Simple queries go to a single ANRA agent with live context.
    """
    # Route complex queries to the multi-agent swarm
    try:
        from amzn_cse_telco_autonomous_network_agents_app.agent.core.swarm import is_complex_query

        if is_complex_query(req.message):
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

        topo = build_live_topology()
        s = topo.get("summary", {})
        nodes = topo.get("k8s_nodes", [])
        edge_nodes = [n for n in nodes if n.get("role") == "edge"]
        region_nodes = [n for n in nodes if n.get("role") == "region"]

        sops = []
        try:
            sop_dir = Path(__file__).resolve().parent.parent.parent / "sops"
            sops = [f.stem for f in sop_dir.rglob("*.md") if f.stem != "TEMPLATE"]
        except Exception:
            pass

        from amzn_cse_telco_autonomous_network_agents_app.agent.event_store import get_recent

        recent_events = get_recent(300)

        mon_stats = build_monitoring_stats_payload()

        alarms_snap = snapshot_alarms()
        execs_snap = snapshot_executions()
        corrs_snap = snapshot_correlations()
        pending_snap = snapshot_pending_approvals()
        alarm_summary = json.dumps(
            [{"name": a["name"], "severity": a["severity"]} for a in alarms_snap[-10:]],
            default=str,
        )
        exec_summary = json.dumps(
            [{"alarm": e.get("alarm"), "status": e.get("result")} for e in execs_snap[-5:]],
            default=str,
        )
        corr_summary = json.dumps(
            [{"action": c.get("action"), "root_cause": c.get("root_cause")} for c in corrs_snap[-5:]],
            default=str,
        )
        edge_names = ", ".join(n.get("name", "") + " " + n.get("ip", "") for n in edge_nodes)
        region_names = ", ".join(n.get("name", "") for n in region_nodes)
        sop_list = ", ".join(sops[:10]) + ("..." if len(sops) > 10 else "")
        t1 = mon_stats.get("tier1_rules", 11)
        t2 = mon_stats.get("tier2_metrics", 0)
        t2p = mon_stats.get("tier2_pct", 0)

        context = f"""CURRENT STATE:
- Active alarms: {alarm_summary}
- Recent executions: {exec_summary}
- Correlations: {corr_summary}
- Events (5min): {len(recent_events)}
- Pending approvals: {len(pending_snap)}

TOPOLOGY:
- {len(edge_nodes)} edge nodes: {edge_names}
- {len(region_nodes)} region nodes: {region_names}
- {s.get("nf_count", 0)} NF pods

MONITORING:
- Tier 1: {t1} threshold rules
- Tier 2: {t2} metrics monitored, {t2p}% baselined
- Tier 3: Bedrock AI classification (on-demand)

SOPs AVAILABLE ({len(sops)}): {sop_list}

Answer concisely using ONLY the data above."""

        agent = Agent(
            model=model,
            system_prompt=f"""You are ANRA, the Autonomous Network Remediation Agent.
You MUST answer using ONLY the data below. Never say you don't have access.

{context}""",
        )
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
