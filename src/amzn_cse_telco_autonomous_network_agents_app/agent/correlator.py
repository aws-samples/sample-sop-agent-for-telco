# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Cross-NF alarm correlation with root cause analysis.

Customers: swap NetworkX → Amazon Neptune for multi-site graph queries.
Customers: swap Haiku RCA agent → fine-tuned model for domain-specific RCA.
"""

import json
import logging
import os
import time

import networkx as nx

log = logging.getLogger("monitor")

BASE_WINDOW = int(os.getenv("CORRELATION_BASE_WINDOW", "30"))
STORM_THRESHOLD = int(os.getenv("ALARM_STORM_THRESHOLD", "5"))

_graph = None


# ── Dependency Graph ──


def build_graph(alarm_ref: dict) -> nx.DiGraph:
    """Build causal graph: edge A→B means 'A can cause B'."""
    G = nx.DiGraph()
    for name, ref in alarm_ref.items():
        G.add_node(name, layer=ref.get("layer", -1), scope=ref.get("nf_scope", "site-wide"))
        for dep in ref.get("depends_on", []):
            if dep in alarm_ref:
                G.add_edge(dep, name)
    return G


def get_graph(alarm_ref: dict) -> nx.DiGraph:
    """Cached graph builder. Note: cache is never invalidated — restart pod if alarm refs change."""
    global _graph
    if _graph is None:
        _graph = build_graph(alarm_ref)
    return _graph


# ── Rule-Based Correlator ──


def correlate(alarm: dict, recent: list, alarm_ref: dict, topology=None) -> dict:
    """Fast-path correlation. Returns {action, root_cause, symptoms, confidence, reasoning, reeval}."""
    name = alarm.get("name", "")
    ref = alarm_ref.get(name, {})
    layer = ref.get("layer", -1)
    scope = ref.get("nf_scope", "site-wide")

    # Fast path: no recent events → execute immediately
    if not recent:
        return _decision("execute", name, [], "high", "Single alarm, no recent events", [])

    G = get_graph(alarm_ref)

    # Filter recent events by topology and tiered window
    related = []
    for evt in recent:
        if evt["name"] == name:
            continue
        if not _is_related(alarm, evt, scope, topology):
            continue
        evt_layer = alarm_ref.get(evt["name"], {}).get("layer", -1)
        window = BASE_WINDOW * max(1, abs(layer - evt_layer))
        if time.time() - evt["ts"] <= window:
            related.append(evt)

    if not related:
        return _decision("execute", name, [], "high", "No related events in window", [])

    # Check if this alarm is a symptom (ancestor exists in related events)
    for evt in related:
        if evt["name"] in G and name in G:
            try:
                if nx.has_path(G, evt["name"], name):
                    return _decision(
                        "suppress", evt["name"], [name], "high", f"{name} is downstream of {evt['name']}", [name]
                    )
            except nx.NetworkXError:
                pass

    # Check if this alarm is root cause (it's ancestor of related events)
    symptoms = []
    for evt in related:
        if name in G and evt["name"] in G:
            try:
                if nx.has_path(G, name, evt["name"]):
                    symptoms.append(evt["name"])
            except nx.NetworkXError:
                pass

    if symptoms:
        return _decision("execute", name, symptoms, "high", f"{name} is root cause of {symptoms}", list(set(symptoms)))

    # Ambiguous — escalate
    return _decision(
        "escalate", name, [], "low", f"No dependency path between {name} and {[e['name'] for e in related]}", []
    )


def correlate_batch(alarms: list, recent: list, alarm_ref: dict, topology=None) -> dict:
    """Storm handler: sort by layer, lowest is root cause."""
    if not alarms:
        return _decision("execute", "", [], "low", "Empty batch", [])

    def get_layer(a):
        return alarm_ref.get(a.get("name", ""), {}).get("layer", 99)

    sorted_alarms = sorted(alarms, key=get_layer)
    root = sorted_alarms[0]
    symptoms = [a["name"] for a in sorted_alarms[1:]]
    return _decision(
        "execute",
        root["name"],
        symptoms,
        "medium",
        f"Alarm storm: {len(alarms)} alarms, lowest layer={get_layer(root)}",
        symptoms,
    )


def rca_investigate(events: list, alarm_ref: dict, topology=None) -> dict:
    """Strands agent for ambiguous correlation. Called only on escalate."""
    try:
        context = _build_context(events, alarm_ref, topology)
        agent = _create_rca_agent()
        result = agent(f"Analyze these correlated alarms and identify the root cause:\n\n{context}")
        response = str(result)
        # Try to parse JSON from response
        if "{" in response:
            import re

            match = re.search(r"\{[^}]+\}", response)
            if match:
                parsed = json.loads(match.group())
                return _decision(
                    "execute",
                    parsed.get("root_cause", events[0]["name"]),
                    [],
                    parsed.get("confidence", "medium"),
                    parsed.get("reasoning", response),
                    [],
                )
        return _decision("execute", events[0]["name"], [], "low", f"RCA: {response[:200]}", [])
    except Exception as e:
        log.debug(f"RCA agent failed: {e}")
        # Fallback: execute lowest-layer alarm
        lowest = min(events, key=lambda e: alarm_ref.get(e.get("name", ""), {}).get("layer", 99))
        return _decision("execute", lowest.get("name", ""), [], "low", f"RCA fallback: {e}", [])


# ── RCA Agent Tools ──

try:
    from strands.types.tools import tool
except ImportError:

    def tool(fn):
        return fn


@tool
def get_event_timeline(window_seconds: int = 120) -> str:
    """Tool: return formatted event timeline from buffer."""
    from amzn_cse_telco_autonomous_network_agents_app.agent.event_store import get_recent

    events = get_recent(window_seconds)
    if not events:
        return "No events in window"
    t0 = events[0]["ts"]
    return "\n".join(
        f"T+{e['ts'] - t0:.0f}s [L{e['layer']}] {e['name']} ({e['severity']}) node={e.get('node', '')} nf={e.get('nf', '')}"
        for e in events
    )


@tool
def get_nf_dependencies(alarm_name: str) -> str:
    """Tool: return depends_on + dependents for an alarm."""
    from amzn_cse_telco_autonomous_network_agents_app.agent.monitor import _alarm_ref

    ref = _alarm_ref.get(alarm_name, {})
    deps = ref.get("depends_on", [])
    G = get_graph(_alarm_ref)
    dependents = [n for n in G.successors(alarm_name)] if alarm_name in G else []
    return f"depends_on: {deps}\ndependents: {dependents}\nlayer: {ref.get('layer', '?')}\nscope: {ref.get('nf_scope', '?')}"


@tool
def get_topology_context() -> str:
    """Tool: return node roles, NF placement, upstream/downstream."""
    try:
        from amzn_cse_telco_autonomous_network_agents_app.agent.topology import get_provider

        tp = get_provider()
        nodes = tp.get_nodes()
        return "\n".join(f"{n['name']}: roles={n.get('roles', [])}, bmc={n.get('bmc_ip', '')}" for n in nodes)
    except Exception:
        return "Topology unavailable"


RCA_SYSTEM_PROMPT = """You are a 5G network root cause analyst. Given correlated alarms, identify the single root cause.
Use tools to check the event timeline, NF dependencies, topology, and pod status.
Respond with JSON: {"root_cause": "alarm_name", "reasoning": "...", "confidence": "high|medium|low"}"""


def _create_rca_agent():
    """Create Strands agent with read-only tools."""
    from strands import Agent

    from amzn_cse_telco_autonomous_network_agents_app.agent.core.model_resolver import (
        build_model,
    )
    from amzn_cse_telco_autonomous_network_agents_app.agent.framework.enums import (
        ModelTier,
    )

    model = build_model(ModelTier.FAST)
    return Agent(
        model=model,
        system_prompt=RCA_SYSTEM_PROMPT,
        tools=[get_event_timeline, get_nf_dependencies, get_topology_context],
    )


def _build_context(events: list, alarm_ref: dict, topology=None) -> str:
    """Format event timeline + dependency info for RCA prompt."""
    lines = [get_event_timeline(300)]
    for e in events:
        lines.append(f"\n{e['name']}: {get_nf_dependencies(e.get('name', ''))}")
    lines.append(f"\nTopology:\n{get_topology_context()}")
    return "\n".join(lines)


# ── Helpers ──


def _is_related(alarm: dict, event: dict, scope: str, topology) -> bool:
    """Check if alarm and event are topologically related."""
    if scope == "site-wide":
        return True
    if scope == "per-node":
        a_node = alarm.get("node_name", "") or alarm.get("node", "")
        e_node = event.get("node", "")
        return a_node and e_node and a_node == e_node
    # per-instance: check topology path
    if topology:
        a_node = alarm.get("node_name", "") or alarm.get("node", "")
        e_node = event.get("node", "")
        if a_node and e_node:
            if a_node == e_node:
                return True
            upstream = topology.get_upstream(a_node)
            affected = topology.get_affected_by(a_node)
            related_names = {n.get("name", "") for n in upstream + affected}
            return e_node in related_names
    return True  # no topology → assume related


def _decision(action, root_cause, symptoms, confidence, reasoning, reeval) -> dict:
    return {
        "action": action,
        "root_cause": root_cause,
        "symptoms": symptoms,
        "confidence": confidence,
        "reasoning": reasoning,
        "reeval": reeval,
    }
