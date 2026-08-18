# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Edge-traversal conditions for the SOP execution graph.

Extracted from sop_graph.py. Each function is a factory that returns a
``check(state) -> bool`` predicate the Strands GraphBuilder evaluates on an
edge. Grouped together because they share one concern: deciding when a graph
edge may be traversed, given the completion state of upstream nodes.

The Strands Graph uses OR-join semantics (any satisfied incoming edge makes a
node ready); these predicates layer the AND-join and retry-limit behavior the
SOP DAG needs on top of that.
"""

from __future__ import annotations

import logging

from strands.multiagent.base import Status
from strands.multiagent.graph import GraphState

logger = logging.getLogger(__name__)

# Markers the node classes emit into their output text and these edge conditions
# scan for. Kept as named constants (not inline literals) because they are a
# contract shared between the producers (EvalNode / CorrectorNode in sop_graph)
# and the consumers here -- a drift between the two silently breaks traversal.
NEEDS_CORRECTION_MARKER = "NEEDS_CORRECTION"
SOP_PATCHED_MARKER = "SOP patched"


def _all_upstreams_passed(terminal_ids: list[str], target: str = ""):
    """AND-join condition: only traverse when ALL upstream terminals have completed.

    The Strands Graph uses OR-join (any edge satisfied → node ready).
    We need AND-join for DAG dependencies. This condition is placed on every
    incoming edge, so whenever any upstream completes, the condition is checked.
    It only returns True when ALL upstreams are done.
    """

    def check(state: GraphState) -> bool:
        satisfied = [tid for tid in terminal_ids if (r := state.results.get(tid)) is not None and r.status == Status.COMPLETED]
        result = len(satisfied) == len(terminal_ids)
        if satisfied:  # Only log when at least one upstream done (avoid noise)
            logger.info(f"AND-join {target}: {len(satisfied)}/{len(terminal_ids)} satisfied={satisfied} → {'PASS' if result else 'WAIT'}")
        return result

    return check


def _corrector_made_changes(corrector_id: str):
    """Condition: only re-run SOP if corrector actually patched the markdown.

    When corrector finds no actionable failures (AGENT_FAULT with nothing to
    fix), it outputs "skipping SOP patch" — no point re-running the same SOP.
    """

    def check(state: GraphState) -> bool:
        r = state.results.get(corrector_id)
        if not r or r.status != Status.COMPLETED:
            return False
        results = r.get_agent_results()
        return any(SOP_PATCHED_MARKER in str(ar.message["content"]) for ar in results if ar.message)

    return check


def _needs_correction(eval_id: str, max_retries: int = 2):
    """Condition: traverse if eval output contains NEEDS_CORRECTION, up to max_retries times."""
    attempts = {"count": 0}

    def check(state: GraphState) -> bool:
        r = state.results.get(eval_id)
        if not r or r.status != Status.COMPLETED:
            return False
        results = r.get_agent_results()
        needs = any(NEEDS_CORRECTION_MARKER in str(ar.message["content"]) for ar in results if ar.message)
        if needs:
            attempts["count"] += 1
            if attempts["count"] > max_retries:
                logger.warning(f"{eval_id}: max correction retries ({max_retries}) reached, skipping")
                return False
        return needs

    return check
