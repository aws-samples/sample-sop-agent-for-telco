# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

import json
import os
from pathlib import Path

from app_state import _alarms, _correlations, _executions, _pending_approvals
from fastapi import APIRouter
from live_topology import build_live_topology
from monitoring_stats import build_monitoring_stats_payload
from pydantic import BaseModel

router = APIRouter(tags=["chat"])


class ChatRequest(BaseModel):
    message: str


@router.post("/api/chat")
async def chat(req: ChatRequest):
    """Chat with ANRA agent — ask about alarms, nodes, SOPs."""
    try:
        import boto3
        from strands import Agent
        from strands.models.bedrock import BedrockModel

        session = boto3.Session(
            profile_name=os.getenv("BEDROCK_PROFILE") or None,
            region_name=os.getenv("BEDROCK_REGION", "us-west-2"),
        )
        model = BedrockModel(
            model_id="us.anthropic.claude-haiku-4-5-20251001-v1:0",
            boto_session=session,
        )

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

        from event_store import get_recent

        recent_events = get_recent(300)

        mon_stats = build_monitoring_stats_payload()

        alarm_summary = json.dumps(
            [{"name": a["name"], "severity": a["severity"]} for a in _alarms[-10:]],
            default=str,
        )
        exec_summary = json.dumps(
            [{"alarm": e.get("alarm"), "status": e.get("result")} for e in _executions[-5:]],
            default=str,
        )
        corr_summary = json.dumps(
            [{"action": c.get("action"), "root_cause": c.get("root_cause")} for c in _correlations[-5:]],
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
- Pending approvals: {len(_pending_approvals)}

TOPOLOGY:
- {len(edge_nodes)} edge nodes: {edge_names}
- {len(region_nodes)} region nodes: {region_names}
- {s.get("nf_count", 0)} NF pods

MONITORING:
- Tier 1: {t1} threshold rules
- Tier 2: {t2} metrics monitored, {t2p}% baselined
- Tier 3: Bedrock AI classification (on-demand)

SOPs AVAILABLE ({len(sops)}): {sop_list}"""

        from sop_executor import kubectl, list_sops, read_sop, list_nodes, check_pod_status

        CHAT_TOOLS = [kubectl, list_sops, read_sop, list_nodes, check_pod_status]

        agent = Agent(
            model=model,
            tools=CHAT_TOOLS,
            system_prompt=f"""You are ANRA, the Autonomous Network Remediation Agent.
You have live tools that you MUST use.

RULES (mandatory):
1. When asked about pods, namespaces, deployments, or cluster state → CALL kubectl tool. NEVER answer from the snapshot.
2. When asked about SOPs → CALL list_sops or read_sop tool.
3. When asked about nodes → CALL list_nodes or check_pod_status tool.
4. The CONTEXT SNAPSHOT below is stale (~30s old) and INCOMPLETE. It only shows 5G NF count, not total pods.
5. If you answer a cluster state question WITHOUT calling a tool, you are giving wrong information.

CONTEXT SNAPSHOT (for background awareness only, DO NOT use to answer state questions):
{context}""",
        )
        result = agent(req.message)
        return {"response": str(result)}
    except Exception as e:
        return {"response": f"Sorry, I couldn't process that: {str(e)[:200]}"}
