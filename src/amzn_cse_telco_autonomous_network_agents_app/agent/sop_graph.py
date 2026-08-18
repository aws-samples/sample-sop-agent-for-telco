# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Graph-based SOP orchestrator using Strands multi-agent Graph pattern.

Fully SOP-agnostic — all dependencies, tools, and model selection are
derived from SOP content at runtime. No hardcoded SOP names or stages.
"""

from __future__ import annotations

import logging
import uuid
from pathlib import Path
from typing import Optional

from strands.multiagent import GraphBuilder

from amzn_cse_telco_autonomous_network_agents_app.agent.sop_executor import (
    setup_eval_telemetry,
)

# Cohesive sibling modules. Re-imported here so build_sop_graph / build_eval_loop
# (and existing callers/tests that reference these on sop_graph) keep working
# through the same names.
from amzn_cse_telco_autonomous_network_agents_app.agent.sop_metadata import (
    parse_sop_metadata,
    resolve_dependencies,
    select_model,
)
from amzn_cse_telco_autonomous_network_agents_app.agent.graph_conditions import (
    _all_upstreams_passed,
    _corrector_made_changes,
    _needs_correction,
)
from amzn_cse_telco_autonomous_network_agents_app.agent.sop_nodes import (
    CorrectorNode,
    EvalNode,
    create_sop_agent,
)

logger = logging.getLogger(__name__)


# The node classes (EvalNode / CorrectorNode / create_sop_agent) now live in
# sop_nodes.py, and model construction + the evals sys.path bootstrap moved with
# them. SOP content analysis lives in sop_metadata.py; graph edge conditions in
# graph_conditions.py. All re-imported above.


# ── Graph Builders ──


def _derive_timeout(metas: list[dict], eval_mode: bool, auto_correct: bool) -> int:
    """Derive graph timeout from SOP complexity. No hardcoded values.

    Per-SOP budget: 60s base + 5s per bash block + 0.5s per line + explicit sleeps, min 120s.
    Eval adds 30s per SOP. Auto-correct multiplies by 2 (re-run cycles).
    """
    total = 0
    for meta in metas:
        per_sop = max(
            120, 60 + meta.get("bash_blocks", 0) * 5 + meta.get("lines", 0) // 2 + meta.get("sleep_seconds", 0)
        )
        if eval_mode:
            per_sop += 30
        total += per_sop
    if auto_correct:
        total *= 2
    return total


def build_sop_graph(
    sop_paths: list[str],
    profile: Optional[str] = None,
    region: str = "us-east-1",
    default_model: str = "haiku",
    fix_mode: bool = False,
    no_steering: bool = False,
    eval_mode: bool = False,
    auto_correct: bool = False,
) -> "Graph":
    """Build a DAG from SOP files. Dependencies and models derived from content."""
    metas = [parse_sop_metadata(p) for p in sop_paths]
    edges = resolve_dependencies(metas)

    # Per-SOP eval contexts — each SOP gets its own session_id so the
    # evaluator only counts tool spans from that specific agent, not all
    # agents running in parallel.
    shared_telemetry = setup_eval_telemetry() if eval_mode else None

    builder = GraphBuilder()

    for meta, sop_path in zip(metas, sop_paths):
        # Per-SOP eval context: shared telemetry, unique session_id
        eval_ctx = None
        if shared_telemetry:
            eval_ctx = {
                "telemetry": shared_telemetry,
                "session_id": uuid.uuid4().hex,
            }

        model = select_model(meta, default_model)
        agent = create_sop_agent(
            sop_path,
            profile=profile,
            region=region,
            model_name=model,
            fix_mode=fix_mode,
            no_steering=no_steering,
            eval_ctx=eval_ctx,
        )
        builder.add_node(agent, meta["stem"])

        # When eval is on, add an EvalNode after each SOP agent
        if eval_mode:
            eval_node_id = f"eval-{meta['stem']}"
            eval_node = EvalNode(eval_ctx, sop_path, name=eval_node_id)
            builder.add_node(eval_node, eval_node_id)
            builder.add_edge(meta["stem"], eval_node_id)

            # Two-stage auto-correct: AGENT_FAULT → re-run with best model
            #                          SOP_FAULT   → patch SOP then re-run
            if auto_correct:
                corrector_id = f"correct-{meta['stem']}"
                corrector = CorrectorNode(sop_path, profile, region, name=corrector_id)
                builder.add_node(corrector, corrector_id)

                # AGENT_FAULT or SOP_FAULT → corrector patches the SOP
                builder.add_edge(eval_node_id, corrector_id, condition=_needs_correction(eval_node_id))
                # After correction → re-run ONLY if corrector actually patched the SOP
                builder.add_edge(corrector_id, meta["stem"], condition=_corrector_made_changes(corrector_id))

    # Determine the "terminal" node for each SOP (for inter-SOP dependency edges)
    # The eval node is always the last to run in the SOP cycle:
    #   SOP agent → eval → (if fail: corrector → SOP re-run → eval again)
    # So eval is always the terminal, regardless of auto_correct.
    terminal = {}
    for meta in metas:
        s = meta["stem"]
        if eval_mode:
            terminal[s] = (f"eval-{s}",)
        else:
            terminal[s] = (s,)

    # Add dependency edges (from terminal of upstream to SOP agent of downstream)
    # The Graph uses OR-join (any satisfied edge → node ready). We need AND-join
    # (ALL upstream deps complete before downstream starts). Fix: add an edge from
    # every upstream terminal, each carrying the SAME compound AND condition that
    # checks ALL terminals. When any upstream completes, its edge fires and the
    # condition checks if all others are also done. Only the last one to complete
    # will see True.
    stem_set = {m["stem"] for m in metas}

    from collections import defaultdict

    deps_by_target: dict[str, list[str]] = defaultdict(list)
    for from_stem, to_stem in edges:
        if from_stem in stem_set and to_stem in stem_set:
            deps_by_target[to_stem].append(from_stem)

    for to_stem, from_stems in deps_by_target.items():
        all_terminals = []
        for fs in from_stems:
            all_terminals.extend(terminal[fs])
        cond = _all_upstreams_passed(all_terminals, target=to_stem)
        for t in all_terminals:
            builder.add_edge(t, to_stem, condition=cond)

    # Entry points = nodes with no incoming edges in this run
    nodes_with_incoming = {to_s for _, to_s in edges if to_s in stem_set}
    for meta in metas:
        if meta["stem"] not in nodes_with_incoming:
            builder.set_entry_point(meta["stem"])

    builder.set_execution_timeout(_derive_timeout(metas, eval_mode, auto_correct))
    logger.info(f"Derived timeout: graph={_derive_timeout(metas, eval_mode, auto_correct)}s from {len(metas)} SOPs")
    if auto_correct:
        builder.reset_on_revisit(True)
        builder.set_max_node_executions(len(metas) * 9)  # 3 cycles per SOP
    builder.set_graph_id("sop-orchestrator")
    graph = builder.build()
    logger.info(
        f"Graph built: {len(graph.nodes)} nodes, {len(graph.edges)} edges, entries={[n.node_id for n in graph.entry_points]}"
    )
    for e in graph.edges:
        logger.debug(f"  Edge: {e.from_node.node_id} -> {e.to_node.node_id} (cond={e.condition is not None})")
    return graph


def build_eval_loop(
    sop_path: str,
    profile: Optional[str] = None,
    region: str = "us-east-1",
    model_name: str = "haiku",
    fix_mode: bool = False,
    no_steering: bool = False,
    max_corrections: int = 2,
) -> "Graph":
    """Build a single-SOP graph with eval feedback loop.

    execute → eval → correct → execute ... (max N cycles)
                  → done (if passing)
    """
    eval_ctx = {
        "telemetry": setup_eval_telemetry(),
        "session_id": uuid.uuid4().hex,
    }

    stem = Path(sop_path).stem
    meta = parse_sop_metadata(sop_path)
    model = select_model(meta, model_name)

    agent = create_sop_agent(
        sop_path,
        profile=profile,
        region=region,
        model_name=model,
        fix_mode=fix_mode,
        no_steering=no_steering,
        eval_ctx=eval_ctx,
    )
    eval_node = EvalNode(eval_ctx, sop_path, name="eval")

    builder = GraphBuilder()
    builder.add_node(agent, stem)
    builder.add_node(eval_node, "eval")

    builder.add_edge(stem, "eval")

    if max_corrections > 0:
        corrector = CorrectorNode(sop_path, profile, region, name="corrector")
        builder.add_node(corrector, "corrector")
        builder.add_edge("eval", "corrector", condition=_needs_correction("eval"))
        builder.add_edge("corrector", stem, condition=_corrector_made_changes("corrector"))

    builder.set_entry_point(stem)
    builder.set_max_node_executions(3 + max_corrections * 3)
    builder.set_execution_timeout(_derive_timeout([meta], True, max_corrections > 0))
    builder.reset_on_revisit(True)
    builder.set_graph_id("sop-eval-loop")
    return builder.build()
